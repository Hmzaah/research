# PTCG AI Battle Challenge Playground — 現状分析・ベースライン・上位攻略プラン

- 作成日: 2026-10-04
- 対象: [The Pokémon Company - PTCG AI Battle Challenge Playground](https://www.kaggle.com/competitions/the-pokemon-company-ptcg-ai-battle-challenge-playground/overview)
- コード: [`competitions/ptcg_playground/`](../../competitions/ptcg_playground/README.md)

## 1. コンペの仕組み（一次情報で確認した点）

| 項目 | 内容 |
|---|---|
| 期間 | 2026-09-29 開始 / 2027-01-01 参加・統合締切 / **2027-01-08 最終提出** / 2027-01-22 順位確定 |
| 形式 | BO3（2 勝先取）、Bradley-Terry 系レーティング（μ, σ）、近いレートと継続マッチング |
| 提出 | `.tar.gz`（ルートに `main.py` + `deck.csv`）、1 日 5 回、**ラダーに残るのは最新 2 提出** |
| 実行環境 | 2 vCPU / 12.2 GiB / `/kaggle_simulations/agent/` |
| 持ち時間 | `kaggle-environments` 1.33.0 の `cabt.json`: `actTimeout=0`, `remainingOverageTime=600`, `bo=3` → **BO3 全体で 600 秒の共有プール** |
| 2 戦目以降 | 終了試合数が奇数のとき `BattleStartReverse`（後手側が先攻/後攻を選択） |
| 失格条件 | 例外・不正な選択・時間切れはその場で負け（`cabt.py` の `interpreter`） |

エンジン（CABT, `libcg.so`）は PyPI の `kaggle-environments` 1.33.0 に同梱されており、本セッションで直接解析・実行した。カード 1,431 種 / 技 1,755 種をエンジンから取得できる。探索 API（`SearchBegin/Step/End`）の ctypes 宣言は `kaggle_environments` 版 `cg/sim.py` に無いため、エージェント側で宣言している。

## 2. リーダーボードと競合の水準

本セッションの実行環境では `www.kaggle.com` への通信がネットワークポリシーで遮断されており、リーダーボードを直接取得できなかった。Web 検索インデックス経由で確認できた範囲:

| 順位 | チーム | スコア |
|---|---|---|
| 1 | Stephen Schott | 1196.0 |
| 2 | OceanMix | 1122.4 |
| 3 | Darren Sheehan | 1064.6 |

本戦（Simulation, 6,807 チーム, μ0 = 600）での参考値:

| 事例 | スコア | 手法 |
|---|---|---|
| 本戦 1 位 | — | 約 224 万パラメータ Transformer を PPO 自己対戦で 4 段階学習。Dragapult ex ×2 / Hydrapple ex ×1 の **デッキ専用モデル** |
| wmh/ptcg-abc | 836 | ルールベース + 行動模倣（Iono's Bellibolt ex） |
| hotorch | 742.8 | ルールベース（上位 24%） |

**結論: 手書きルールだけでは 700〜850 帯。1,100〜1,200 の上位には「探索」か「デッキ専用の学習済み方策」が必要。**

本戦終盤のメタ（2026-08-12〜14）: Grimmsnarl 19.7% / Dragapult 19.5% / Alakazam 13.8% / Lopunny 13.0% / Hydrapple・Meganium 9.5% / Kangaskhan・Crustle 4.9% / Lucario 4.4% ほか（11 アーキタイプで 95.8%）。

## 3. 作ったベースライン

```
deck.csv ─► agent(obs) ─┬─ legalize()  … 全応答を合法な形に矯正（例外時も必ず合法手）
                        ├─ RolloutSearch … 決定化ロールアウト探索（MAIN と重要な単一選択）
                        │     ├ 非公開カードのサンプリング（自山札・サイド・相手山札/手札/サイド）
                        │     │   相手は既知メタ 17 デッキと照合、BO3 の前の試合で見たカードも記憶
                        │     ├ 各候補手を 1 手進め、以降は両者ヒューリスティックで「次の自分の番の頭」まで
                        │     ├ 盤面評価（サイド差・盤面・エネルギー・攻撃可能性・手札・山切れ）
                        │     └ 共通乱数 + 逐次半減、残り時間から 1 手の予算を算出
                        └─ Policy      … 全 49 SelectContext 対応のヒューリスティック（ロールアウト兼用）
```

### 計測結果（ローカル、Kaggle と同じ BO3 進行・600 秒持ち時間）

| 比較 | 結果 |
|---|---|
| ヒューリスティック vs ランダム（Dragapult 同型） | 試合 95%（デッキ切れ対策後、ゲーム勝率 79%→92%） |
| ヒューリスティック vs 「常に先頭の選択肢」 | 試合 100% |
| 探索 vs ヒューリスティック（Dragapult 同型） | 試合 62〜69% |
| 探索（Dragapult）vs ヒューリスティック（Archaludon） | 試合 93.8%（ヒューリスティック同士だと 52.5%） |
| 探索（Dragapult）vs ヒューリスティック（Froslass） | 試合 62.5%（同 30.0%） |
| 先攻 vs 後攻（6 デッキ × 200 試合） | 全デッキで先攻が有利（ゲーム勝率 51.5〜59.5%）→ 常に先攻を選ぶ |

### デッキ選定

探索エージェントで各候補デッキを操縦し、メタ 17 デッキ（ヒューリスティック操縦）と各 4 試合ずつ対戦:

| 候補 | 試合勝敗 | 勝率 |
|---|---|---|
| Cynthia's Garchomp ex | 66-2 | 97.1% |
| Mega Froslass ex + Mega Starmie ex | 65-3 | 95.6% |
| Marnie's Grimmsnarl ex | 62-5 | 92.5% |
| Mega Starmie ex（Cinderace） | 58-10 | 85.3% |
| Dragapult ex | 53-15 | 77.9% |
| Archaludon ex | 52-16 | 76.5% |

上位 3 デッキの探索同士の直接対決（各 16 試合、両先後）:

| 対戦 | 試合 | ゲーム |
|---|---|---|
| Garchomp vs **Froslass** | 3-13 | 10-28 |
| **Garchomp** vs Grimmsnarl | 14-2 | 30-10 |
| **Froslass** vs Grimmsnarl | 13-3 | 26-10 |

→ **提出デッキ: Mega Froslass ex + Mega Starmie ex（水単, `decks/wmh_froslass.csv`）**

- 根拠: ヒューリスティック総当たりでも 17 デッキ中 1 位（77.1%）、探索同士の直接対決で 2 戦 2 勝
- 構成: 4 Snorunt / 4 Staryu / 3 Mega Froslass ex / 3 Mega Starmie ex / 4 Buddy-Buddy Poffin / 4 Energy Search / 3 Pokégear 3.0 / 2 Switch / 2 Mega Signal / 1 Night Stretcher / 4 Salvatore / 4 Lillie's Determination / 3 Wally's Compassion / 2 Boss's Orders / 2 Hilda / 1 Black Belt's Training / 2 Gravity Mountain / 9 基本水エネルギー / 1 Mist Energy / 1 Legacy Energy / 1 Ignition Energy
- 注意: 評価相手はローカルのヒューリスティック/探索エージェントであり、ラダー上の強い RL エージェントとの相性は未検証。ラダー結果で見直す

### 失敗から分かったこと（再発防止済み）

1. **`sys.path` の罠（Kaggle で即死級）**: `kaggle_environments` はエージェントのディレクトリを `exec()` 中だけ `sys.path` に追加し、終わると外す。遅延 import していたため、ローカルでは動くのに検証環境では `ModuleNotFoundError` → 自明な方策にフォールバックしていた。`main.py` で常に自前で `sys.path` に追加し、読み込み時に import するよう修正。新しい cwd・新しいプロセスで再現するテストを追加し、旧コードで失敗することを確認済み。
2. **メモリリーク**: `AgentStart()` で確保される探索ハンドルは解放されない。エージェント生成ごとに確保していたため長時間の評価で 3.7 GB に達し OOM。1 プロセス 1 ハンドルに変更し、5 試合連続で RSS ≒ 100 MB 一定を確認。
3. **デッキ切れ負け**: ドロー系特性を毎ターン使い山札切れ。山札残量に応じてドロー系の評価を下げる。
4. **詰み**: エネルギー 0 のポケモンがバトル場で動けなくなる。逃げるためのエネルギー付与を評価。
5. **学習済み価値関数（6 万試合・95 万局面、検証精度 75.7%）を探索の評価に使うと逆に弱くなった**（ヒューリスティック相手 46% vs 手書き評価 67%）。結果予測は得意でも、ほぼ同じ候補局面の順位付けは苦手。既定は手書き評価、価値関数は今後の改善用に残している。
6. **思考時間を増やしても強くならない**（0.8 秒/手 vs 0.2 秒/手で 5-11、0.3 秒 vs 0.1 秒で 10-10）。既定の上限は 0.3 秒（BO3 で最大 40 秒程度しか使わず安全）。評価関数の偏りが支配的で、サンプルを増やすほど偏った手を確信して選ぶ。→ 評価関数の改善が最優先課題。

## 4. 上位（1,100〜1,200）を狙うロードマップ

優先度順。各ステップは `tools/arena.py` / `tools/gauntlet.py` で採否を判断し、良いものだけを提出する（1 日 5 回、最新 2 つがラダーに残る）。

1. **今すぐ: ベースラインを提出してラダーの実力値を得る**（2 枠: 探索版 + デッキ違いまたは予算違い）。ローカル評価とラダーの相関を確かめる。
2. **評価関数の改善（最大のレバー）**
   - 手書き評価の重みを、ローカル対戦の勝率を目的関数に自動調整（CMA-ES 等）。
   - 価値関数を「探索エージェント同士の対局」から学習し直し（expert iteration）、候補比較に効く順位学習の損失を併用。
   - 評価点を「次の自分の番の頭」だけでなく「相手の次の攻撃後」まで伸ばすか比較。
3. **デッキ専用化（本戦 1 位の知見）**: 提出デッキの主要カード（例: Mega Froslass ex の特性・Mega Starmie ex の技、サポートの使い順）に専用ルールと候補手の絞り込みを入れる。探索の候補数が減るぶん 1 候補あたりのサンプルが増える。
4. **相手モデル**: Kaggle の日次上位エピソードデータセット（`kaggle/pokemon-tcg-ai-battle-episodes-*`）から実際のメタデッキと行動を取得し、決定化と相手方策（行動模倣）に使う。**要: 実行環境から `www.kaggle.com` への通信許可と Kaggle API 資格情報**。
5. **時間の使い切り**: 現在は BO3 で 1 エージェント約 30〜150 秒しか使っていない。評価関数が良くなれば上限を引き上げる（600 秒・予備 45 秒の範囲で予算を自動配分する実装は済み）。
6. **強化学習（上限が最も高い）**: 本戦 1 位同様、デッキ固定で PPO 自己対戦。エンジンは 1 コアで約 1 万ステップ/秒と高速なので、GPU（Kaggle Notebook 等）と組み合わせれば締切（1/8）までに十分回せる。探索と組み合わせ（方策で候補を絞り、価値で評価）れば相乗効果が見込める。

## 5. 運用チェックリスト（毎回の提出前）

- [ ] `python3 -m unittest discover -s tests -v`（合法性・堅牢性・Kaggle 方式ロード）
- [ ] `python3 tools/package.py --deck agent/deck.csv`（デッキ 60 枚・エンジン受理・サイズ）
- [ ] `python tools/validate.py build/submission.tar.gz`（実インタプリタで自己対戦、stderr なし・全員 DONE）
- [ ] `tools/arena.py` で前回提出版に勝ち越していること（両先後・BO3・16 試合以上）

## 出典

- [Playground リーダーボード](https://www.kaggle.com/competitions/the-pokemon-company-ptcg-ai-battle-challenge-playground/leaderboard)（検索インデックス経由）
- [本戦 Simulation リーダーボード](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle/leaderboard)
- [本戦 1 位ライトアップ "Aim to Be a Pokémon Master"](https://www.kaggle.com/competitions/pokemon-tcg-ai-battle-challenge-strategy/writeups/new-writeup-1784257142000)
- [wmh/ptcg-abc](https://github.com/wmh/ptcg-abc)（メタデッキのリスト）
- [hotorch/ptcg-ai-battle-strategy](https://github.com/hotorch/ptcg-ai-battle-strategy)
- [BartvonMeijenfeldt/kaggle_pokemon_tcg_ai_battle](https://github.com/BartvonMeijenfeldt/kaggle_pokemon_tcg_ai_battle)（メタ集計、探索 API の引数）
- [Jun-Morita/kaggle-ptcg-ai-battle](https://github.com/Jun-Morita/kaggle-ptcg-ai-battle)
- [kaggle-environments（PyPI）](https://pypi.org/project/kaggle-environments/)
