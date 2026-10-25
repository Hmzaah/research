# PTCG AI Battle Challenge Playground — ベースラインエージェント

Kaggle「The Pokémon Company - PTCG AI Battle Challenge Playground」（2026-09-29〜2027-01-08、BO3・Bradley-Terry ラダー）向けのエージェント一式。
戦略・リーダーボード分析・上位を狙うロードマップは [`docs/plans/ptcg-playground-strategy.md`](../../docs/plans/ptcg-playground-strategy.md) を参照。

## 構成

```
agent/                  提出物のソース（tar.gz のルートになる）
  main.py               Kaggle エントリ（最後に定義された callable = agent）
  deck.csv              提出デッキ（60 枚、カード ID 1 行 1 枚）
  ptcg/
    engine.py           libcg（CABT エンジン）の ctypes ラッパー: カード DB / 探索 API / ローカル対戦
    cards.py            カード DB から導出する静的知識（エネルギー計算・ダメージ推定など）
    policy.py           全 SelectContext 対応のヒューリスティック方策（高速・ロールアウト兼用）
    search.py           決定化ロールアウト探索（SearchBegin/SearchStep, 逐次半減, 600s 予算管理）
    agent.py            デッキ選択・探索/方策の振り分け・合法手ガード（例外時も必ず合法手を返す）
    features.py / value.py   学習済み価値関数のコード（実験用・既定では無効。重みは tools/train_value.py でローカル生成し、コミット・提出しない）
    meta_decks.json     既知メタデッキ（相手の非公開カード推定に使用）
decks/                  メタデッキ 17 種（評価用の対戦相手プール）
tools/
  fetch_engine.sh       kaggle-environments の wheel から CABT エンジン（cg/）を vendor/ に取得
  arena.py              Kaggle の cabt インタプリタと同じ BO3 進行・600s 持ち時間でのローカル対戦
  roundrobin.py         デッキ総当たり（同一エージェント）
  gauntlet.py           候補デッキ × 全メタデッキ
  watch.py / diagnose.py  1 局の意思決定を可読表示 / 敗因集計
  gen_data.py / train_value.py  価値関数の自己対戦データ生成・学習（numpy）
  package.py            提出 tar.gz の作成（デッキ検証・サイズ検査込み）
  validate.py           kaggle_environments で Kaggle の検証エピソード（自己対戦）を再現
tests/test_agent.py     合法性・堅牢性・Kaggle ロード方式のテスト
```

## 使い方

```bash
cd competitions/ptcg_playground
tools/fetch_engine.sh                                   # vendor/cg を取得（初回のみ）
cp -r vendor/cg agent/cg                                # ローカル実行用（git 管理外）
python3 -m unittest discover -s tests -v                # テスト
python3 tools/arena.py --a ours:decks/wmh_froslass.csv --b heur:decks/wmh_dragapult.csv -n 20 -j 4
python3 tools/package.py --deck agent/deck.csv          # build/submission.tar.gz
python tools/validate.py build/submission.tar.gz        # 要 kaggle-environments（venv 推奨）
```

提出は Kaggle のコンペページ「Submit Agent」から `build/submission.tar.gz` をアップロードする（1 日 5 回まで、最新 2 提出がラダーに参加）。

## 設計上の要点（Kaggle 実行環境の仕様に基づく）

- `main.py` は `exec()` で読み込まれ **最後に定義された callable** がエージェントになる。`__file__` は未定義なので `deck.csv` と `ptcg/` の位置から自ディレクトリを特定する。
- 持ち時間は `actTimeout=0`・`remainingOverageTime=600` で **BO3 全体で 600 秒**。探索は残り時間から 1 手あたりの予算を算出し、上限（既定 0.3 秒。0.8 秒は計測上むしろ弱かった）と 45 秒の予備を設ける。
- 不正な応答・例外・時間切れはその場で負け。`legalize()` が全応答を合法な形（重複なし・範囲内・min/max 数）に矯正し、探索失敗時はヒューリスティックへ、ヒューリスティック失敗時は先頭合法手へフォールバックする。
- エンジンの JSON の `option.playerIndex` は「カードの持ち主」。`select.deck` があれば山札からの選択肢の index はそのリストを指す。
- 相手のデッキは BO3 の 3 戦で不変なので、公開されたカードを試合をまたいで記憶し、探索時の非公開カード推定に使う。

## データの出典

- `decks/wmh_*.csv`: [wmh/ptcg-abc](https://github.com/wmh/ptcg-abc) の各エージェントの `deck.csv`、`decks/bart_*.csv`: [BartvonMeijenfeldt/kaggle_pokemon_tcg_ai_battle](https://github.com/BartvonMeijenfeldt/kaggle_pokemon_tcg_ai_battle) のデッキ（カード ID の並びのみ。コードは流用していない）
- エンジン: PyPI の `kaggle-environments`（`tools/fetch_engine.sh` で取得、リポジトリには含めない）
