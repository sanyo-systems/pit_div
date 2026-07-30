# DivWorkStandard4

## フォルダー構成

- `main.py`
  - アプリ起動エントリポイント
- `updater.py`
  - 更新適用専用の起動ファイル
- `app/`
  - アプリ本体のモジュール群
  - `top.py`, `app_update.py`, `app_metadata.py`, `ini_handler.py`, `csv_watcher.py`
- `config/`
  - `setting.example.ini`: 共有用の設定サンプル
  - `version.json`: アプリのローカル版数
  - `manifest.example.json`: 更新マニフェストのサンプル
- `data/`
  - `camera_data.example.json`: カメラ定義サンプル
  - `ro_data.example.json`: 工場・炉定義サンプル
- `packaging/`
  - PyInstaller の spec ファイル
- `scripts/`
  - リリース生成スクリプト

## GitHub に含めないもの

- 実運用の `config/setting.ini`
- 実運用の `data/camera_data.json`
- 実運用の `data/ro_data.json`
- ビルド成果物、ログ、仮想環境
