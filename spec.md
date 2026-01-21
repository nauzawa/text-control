# Gemini Voice Assistant 改修仕様書

## 概要
現在の `chat.py` を改修し、Gemini アプリ版のような「思考（Thinking）」プロセス、「Web検索（Grounding）」機能、および音声認識の強化とマルチプラットフォーム対応を追加する。

## 改修機能一覧

### 1. モデルのアップグレードと構成変更
- **現状**: `gemini-2.5-flash-lite` 固定。
- **改修**:
  - `.env` で使用するモデルを複数設定可能にする（例: メインモデル、Thinkingモデル）。
  - **段階的生成フロー**:
    1. まず「低コストモデル」で回答を試みる。
    2. 必要に応じて「高機能モデル（Thinking/Complex）」や「Grounding」を使用するロジックを検討、またはユーザー指示により切り替える。
    - ※ グラウンディング機能を使う場合は、原則として高機能モデルを使用する。
  - **Thinking 対応**: 思考プロセスを出力するモデル（`gemini-2.0-flash-thinking-exp` 等）への対応。

### 2. Web検索機能 (Google Search Grounding) の追加
- **機能**: ユーザーの質問に対して、知識不足や最新情報が必要な場合に Web 検索を行う。
- **実装**: `google-generativeai` の `tools` に `google_search` を組み込む。
- **挙動**: モデルが必要と判断した場合（または明示的な指示）に検索を実行し、結果を回答に統合する。

### 3. MCP (Model Context Protocol) サーバ連携
- **機能**: 外部の MCP サーバと接続し、そのツールを Gemini から利用可能にする。
- **実装**: 既存の MCP 接続ロジックを維持・強化し、複数のサーバに対応できるようにする（必要であれば）。
- **設定**: `.env` で接続コマンド管理。

### 4. 音声認識 (STT) エンジンの強化
- **機能**: 音声認識エンジンを切り替え可能にする。
- **対応エンジン**:
  1. `SpeechRecognition` (Google Web Speech API 等) - 既存、軽量。
  2. `Whisper` (OpenAI/Local) - 高精度。
- **設定**: `.env` のフラグ `STT_ENGINE` (例: `google` or `whisper`) で切り替え。

### 5. マルチプラットフォーム対応 (Windows & Linux)
- **現状**: Windows に特化したパス記述やコマンド呼び出し（`speak.py` の呼び出し等）がある可能性。
- **改修**:
  - `os.name` や `platform` モジュールを用いて OS を判別。
  - **Windows**: `pythonw` や `.bat`、`pyttsx3`/SAPI 対応を維持。
  - **Linux (Ubuntu)**:
    - パス区切りの適切な処理（`os.path.join` 利用徹底）。
    - 音声合成: `espeak` や `gTTS`、または `pyttsx3` の Linux ドライバ対応。
    - その他 OS 固有コマンドの分岐実装。
    - ※ 検証は不要だが、実装コードとして Linux 分岐を含める。

### 6. システムプロンプトと出力形式
- **要件**: 最終出力は JSON (`display_text`, `speech_text`) 形式。
- **課題**: Thinking プロセスや検索結果のテキストが混ざるとパースエラーになる。
- **対策**:
  - Thinking モデルの出力（思考部分）と回答部分を分離して処理する。
  - 検索結果を含めた回答を JSON 内の `display_text` に整形して格納するよう強く指示する。

## コンフィグレーション (.env 追加・変更)
- `GEMINI_MODEL_NORMAL`: 通常会話用 (例: `gemini-2.0-flash-lite`)
- `GEMINI_MODEL_HIGH`: 高度な推論・検索用 (例: `gemini-2.0-flash`)
- `USE_GOOGLE_SEARCH`: `true` / `false`
- `STT_ENGINE`: `google` / `whisper`
- `MCP_SERVER_COMMAND`: (既存維持)
