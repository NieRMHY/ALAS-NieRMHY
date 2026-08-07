# AzurPilot — アズールレーン自動化支援ツール

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/简体中文-中文-blue?style=flat-square" alt="简体中文"></a>
  <a href="README.zh-TW.md"><img src="https://img.shields.io/badge/繁體中文-繁體-green?style=flat-square" alt="繁體中文"></a>
  <a href="README.en.md"><img src="https://img.shields.io/badge/English-English-red?style=flat-square" alt="English"></a>
  <a href="README.ja.md"><img src="https://img.shields.io/badge/日本語-日本語-orange?style=flat-square" alt="日本語"></a>
  <a href="README.ko.md"><img src="https://img.shields.io/badge/한국어-한국어-violet?style=flat-square" alt="한국어"></a>
</p>

<p align="center">
  <img src="doc/logo.webp" alt="AzurPilot Logo" width="400">
</p>

<p align="center">
  <strong><a href="https://alas.nanoda.work/">AzurPilot 公式サイト</a></strong> ｜ アズールレーン自動化スクリプト・大世界侵蝕ループ・マルチプラットフォーム対応
</p>

<p align="center">
  <a href="https://deepwiki.com/wess09/AzurPilot">
    <img src="https://deepwiki.com/badge.svg" alt="DeepWiki" height="22">
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.14-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/github/license/wess09/AzurPilot?style=flat-square&label=License&color=2ea44f" alt="License">
  <img src="https://img.shields.io/github/stars/wess09/AzurPilot?style=flat-square&label=Stars&color=ffcc00" alt="Stars">
  <img src="https://img.shields.io/github/forks/wess09/AzurPilot?style=flat-square&label=Forks&color=58a6ff" alt="Forks">
  <img src="https://img.shields.io/github/issues/wess09/AzurPilot?style=flat-square&label=Issues&color=f85149" alt="Issues">
</p>

<p align="center">
  <img src="https://img.shields.io/github/last-commit/wess09/AzurPilot?style=flat-square&label=Last%20Commit&color=8b949e" alt="Last Commit">
  <img src="https://img.shields.io/github/commit-activity/m/wess09/AzurPilot?style=flat-square&label=Commit%20Activity&color=8957e5" alt="Commit Activity">
  <img src="https://img.shields.io/github/repo-size/wess09/AzurPilot?style=flat-square&label=Repo%20Size&color=orange" alt="Repo Size">
  <img src="https://img.shields.io/github/languages/top/wess09/AzurPilot?style=flat-square&label=Top%20Language&color=3776AB" alt="Top Language">
</p>

<p align="center">
  <img src="https://img.shields.io/github/contributors/wess09/AzurPilot?style=flat-square&label=Contributors&color=00b4d8" alt="Contributors">
  <img src="https://img.shields.io/github/issues-pr/wess09/AzurPilot?style=flat-square&label=Pull%20Requests&color=ffb703" alt="Pull Requests">
  <img src="https://img.shields.io/github/issues-pr-closed/wess09/AzurPilot?style=flat-square&label=PRs%20Closed&color=2ea44f" alt="Closed Pull Requests">
</p>

<div align="center">
  <a href="https://alas.nanoda.work/">
    <img src="https://img.shields.io/badge/Web-ダウンロード-blue?style=for-the-badge&logo=google-chrome&logoColor=white" />
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;
  <a href="https://join.nanoda.work/#/">
    <img src="https://img.shields.io/badge/交流群-QQ-red?style=for-the-badge&logo=tencent-qq&logoColor=white" />
  </a>
</div>

## プロジェクト概要

AzurPilot は [AzurLaneAutoScript](https://github.com/LmeSzinc/AzurLaneAutoScript) をベースに改変されたアズールレーン自動化支援ツールです。元プロジェクトのコア機能を維持しつつ、複数のブランチ、機能改善、実験的な機能を統合しています。ADB/uiautomator2 で Android エミュレータを操作し、スクリーンショット認識・画像マッチング・OCR によりゲームタスクを自動実行します。CN/EN/JP/TW の4サーバーに対応しています。

> **ご注意**: 本プロジェクトのコードはほぼ AI によって生成・補助されています。不確実性が高いため、修正の [Pull Request](https://github.com/wess09/AzurPilot/pulls) を歓迎します。

**[AzurPilot 公式サイト](https://alas.nanoda.work/)** で機能の詳細をご確認いただくか、**[ダウンロードページ](https://alas.nanoda.work/download.html)** から最新版を入手してください。

## GUI プレビュー

<div align="center">
  <img src="doc/GUI.png" alt="GUI Preview" width="800">
</div>

## クイックスタート

> 💡 **推奨**: [AzurPilot ダウンロードページ](https://alas.nanoda.work/download.html) からお使いのプラットフォームのランチャーを入手してください。Python 環境を同梱しており、すぐに利用できます。

### Linux ワンクリック導入

```shell
curl -fsSL https://alas.nanoda.work/install/deploy-image.sh | sudo -E bash
```

### ソースコードからの実行

本プロジェクトは `uv` とプロジェクトルートの `.venv` で Python 環境を管理しています（Python >= 3.14 が必要）。リリース版ランチャーには uv、Python、ADB、Git が同梱され、依存関係が `.venv` に同期されます。ソースから開発する場合は uv をインストールしてから実行します：

```bash
uv sync --frozen --no-dev
uv run python gui.py
```

起動後、ブラウザで `http://127.0.0.1:25548` を開くと WebUI にアクセスできます。

## 重要なお知らせ

- 本プロジェクトには大量の自動化ロジックと画像認識機能が含まれています。使用前に[ゲーム内設定](#使用前の設定)が完了していることを確認してください。完了していない場合、認識失敗、処理の異常、タスク実行不能などの問題が発生する可能性があります。
- 本プロジェクトには実験的な機能が含まれており、未知の問題が存在する可能性があります。使用前に設定をバックアップし、異常に気づいたら速やかにご報告ください。

## 使用前の設定

使用前に、以下の基準に従ってゲーム内設定を変更する必要があります。

パス: メインメニュー → 右下の設定 → 左サイドバーのオプション。

| 設定名 | 推奨値 |
| --- | --- |
| フレームレート設定 | 60 FPS |
| 大型作戦設定、TB チュートリアルの削減 | オン |
| 大型作戦設定、自律時にアイテムを自動提出 | オン |
| 大型作戦設定、安全海域で自律をデフォルトオン | オフ |
| ストーリー自動再生 | オン |
| ストーリー自動再生速度調整 | 特急 |
| 待機モード設定、待機モードを有効化 | オフ |
| その他の設定、重複キャラクター取得の通知 | オフ |
| その他の設定、快速交換の再確認ダイアログ | オフ |
| その他の設定、決算キャラクターの表示 | オフ |

### 大型作戦設定

パス: 大型作戦 → 右上のレーダー → 指令モジュール → 潜水艦支援。

| 設定名 | 推奨値 |
| --- | --- |
| X 消費時に潜水艦出撃 | チェックを外す |

### ワンクリック退役設定

パス: メインメニュー → 右下の建造 → 左サイドバーの退役 → 左側の歯車アイコン → ワンクリック退役設定。

| 設定名 | 推奨値 |
| --- | --- |
| 選択優先度 1 | R |
| 選択優先度 2 | SR |
| 選択優先度 3 | N |
| 満凸の同名艦船を所持時、退役条件を満たす同名艦船を何隻残すか | 残さない |
| 満凸の同名艦船を所持していない時、退役条件を満たす同名艦船を何隻残すか | 満凸に必要な数または残さない |

### 画像認識の注意事項

認識に影響を与える可能性がある以下のものを削除してください：

- キャラクターの装備
- キャラクターのスキン
- UI 要素を隠す可能性のあるカスタム表示内容

これらは画像認識結果に影響を与え、自動化処理に異常を引き起こす可能性があります。

## MCP サービス

AzurPilot は MCP サービスを提供しており、MCP 対応のクライアントやツールから呼び出すことで、Agent で AzurPilot を簡単に管理できます。

> MCP サービスはデフォルトで WebUI と一緒に起動し、`/mcp` パス（WebUI のデフォルトポート 25548）にマウントされます。また、`uv run python mcp_server_sse.py` で単独実行も可能です（単独ポート 22268）。

### ローカル接続設定

```json
{
  "mcpServers": {
    "alas": {
      "url": "http://127.0.0.1:25548/mcp/sse"
    }
  }
}
```

### クラウドサーバーまたはイントラネット接続設定

```json
{
  "mcpServers": {
    "alas": {
      "url": "http://[IP_ADDRESS]:25548/mcp/sse"
    }
  }
}
```

`[IP_ADDRESS]` を実際のサーバーアドレスまたはイントラネットアドレスに置き換えてください。WebUI のポートを変更した場合は、URL 内のポートも同様に置き換えてください。

### MCP ツール一覧

現在利用可能な MCP ツールは全部で 18 個です。

| カテゴリ | ツール名 | 機能 |
| --- | --- | --- |
| インスタンス管理 | `list_instances` | すべてのインスタンスを一覧表示 |
| | `get_status` | インスタンスの状態を取得 |
| | `start_instance` | インスタンスを起動 |
| | `stop_instance` | インスタンスを停止 |
| タスク管理 | `list_tasks` | すべてのタスクを一覧表示 |
| | `get_task_help` | タスクのヘルプを取得 |
| | `trigger_task` | タスクをトリガー |
| | `get_scheduler_queue` | スケジューラキューの取得 |
| | `clear_scheduler_queue` | スケジューラキューをクリア |
| 監視と情報 | `get_current_running_task` | 現在実行中のタスクを取得 |
| | `get_resources` | リソース状態を取得 |
| | `get_config` | インスタンス設定を取得 |
| | `get_recent_logs` | 最近のログを取得 |
| | `get_screenshot` | スクリーンショットを取得 |
| 設定管理 | `update_config` | 設定を更新 |
| メンテナンスツール | `restart_emulator` | エミュレータを再起動 |
| | `restart_adb` | ADB を再起動 |
| | `update_alas` | AzurPilot を更新 |

## マルチプラットフォームランチャー

> 📥 [AzurPilot 公式サイト](https://alas.nanoda.work/download.html) から Windows / macOS / Linux ランチャーをダウンロード

<div align="center">
  <img src="doc/loading.png" alt="loading" width="500" />
  <p>起動読み込み画面</p>
  <img src="doc/GUI.png" alt="GUI" width="500" />
  <p>Windows クライアント画面</p>
  <img src="doc/macGUI.png" alt="macGUI" width="500" />
  <p>Mac クライアント画面</p>
</div>

ランチャーのプロジェクト：[GitHub](https://github.com/wess09/alas-launcher)・元プロジェクト [ALAS Launcher: 新型の AzurLaneAutoScript ランチャー](https://github.com/swordfeng/alas-launcher)

変更内容：

1. トレイ対応を追加
2. Windows ネイティブ通知
3. GUI スタイルの美化
4. uv 化
...

## コントリビューター

本プロジェクトは AzurLaneAutoScript とそのコミュニティフォークをベースに開発を続けているため、コントリビューター一覧には本リポジトリへの直接の貢献者だけでなく、上流プロジェクトや関連フォークの原作者も含まれます。

*本プロジェクトの貢献者リスト

<a href="https://github.com/wess09/AzurPilot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=wess09/AzurPilot&max=1000" alt="AzurPilot Contributors">
</a>

*ランチャープロジェクトの貢献者リスト

<a href="https://github.com/wess09/alas-launcher/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=wess09/alas-launcher&max=1000" alt="Launcher Contributors">
</a>

*ALAS 元プロジェクトの貢献者リスト

<a href="https://github.com/LmeSzinc/AzurLaneAutoScript/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=LmeSzinc/AzurLaneAutoScript&max=1000" alt="AzurLaneAutoScript Contributors">
</a>

## 関連リンク

- [AzurPilot 公式サイト](https://alas.nanoda.work/) — プロジェクト紹介、機能詳細、アズールレーン自動化ソリューション
- [AzurPilot ダウンロードページ](https://alas.nanoda.work/download.html) — Windows / macOS / Linux 版のアズールレーンスクリプトツールをダウンロード
- [GitHub リポジトリ](https://github.com/wess09/AzurPilot) — ソースコード、Issue、Pull Request
- [QQ 交流群](https://join.nanoda.work/#/) — アズールレーン自動化コミュニティ
- [AzurLaneAutoScript 上流プロジェクト](https://github.com/LmeSzinc/AzurLaneAutoScript) — ALAS オリジナル版
- [AzurPilot ラズベリーパイ版](https://github.com/nnieie/AzurPilot) — ラズベリーパイ / Termux 実機向けの AzurPilot CN デプロイ版

## 開発と貢献

本プロジェクトはほぼ完全に VibeCoding の産物です。不備がありましたらご容赦ください。Issue や Pull Request でのフィードバック、修正、ドキュメント改善を歓迎します。

### 開発環境

```bash
uv sync --frozen        # .venv を作成/同期（開発用依存関係を含む）

# コードチェック（CI は ruff の緩い設定を使用 — 致命的な構文エラーと未定義名のみチェック）
uv run ruff check . --select E9,F63,F7,F82 --ignore F821,F722

# テスト（約160個のユニットテスト）
uv run python -m unittest discover -s tests

# 設定生成（設定 YAML ファイルを変更した後は必ず実行）
uv run -m module.config.config_updater
```

### 使用した開発ツールとモデル

本プロジェクトの開発では、複数の AI モデルと開発ツールを使用しました。

**AI モデル：**

| | | |
| --- | --- | --- |
| Gemini | GPT | Claude |
| GLM | MiMo | DeepSeek |
| Kimi | Qwen | DouBao |

**開発ツール：**

| | | |
| --- | --- | --- |
| Claude Code | Codex | Cursor | Antigravity |
| TRAE | ZCode | OpenCode | MiMoCode |


## ライセンス

本プロジェクトは元プロジェクトおよび関連する上流プロジェクトのライセンス要件に従います。ランチャープロジェクトは GPL-3.0 ライセンスでオープンソース化されています。

本プロジェクトが依存する関連プロジェクトのライセンスは /licenses にあります。

本プロジェクトを使用・変更・配布する際は、関連する上流プロジェクトのライセンス要件も遵守してください。

## スポンサー

<p align="center">
  <a href="https://afdian.com/a/miaonaa">
    <img src="doc/afdian.jfif" alt="爱发电" width="200">
  </a>
  <br>
  <b>本プロジェクトを支援（サーバー費用や新モデルのトレーニングなどに使用）</b>
</p>
