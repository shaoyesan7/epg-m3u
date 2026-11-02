# epg-m3u

为你的 IPTV 直播源自动构建 **EPG（XMLTV 节目单）**，支持 **过去 7 天回放 + 未来 3 天预告**，由 GitHub Actions 每天自动刷新。

> 配套 App：云影空蒙 / TVBox / 任何支持 XMLTV 的 IPTV 播放器。

## 产物

| 文件 | 说明 |
|---|---|
| `epg.xml` | XMLTV 全量（~7–12 MB） |
| `epg.gz` | 压缩版（~300–600 KB，**推荐填进 App 的 EPG 接口**） |

## 快速开始

1. 把要匹配的 M3U 放到 `m3u/` 目录（本仓库自带示例 `m3u/直播源.m3u`）
2. 本地生成一次：
   ```
   python3 epg_build.py --m3u m3u/直播源.m3u --out epg/epg.xml --gzip --autofill
   ```
3. 把 `epg.xml` / `epg.gz` 提交进仓库
4. 在 GitHub 仓库 → **Settings → Pages → Source = GitHub Actions**
5. 把以下地址填进云影空蒙的 EPG 接口：
   ```
   https://<你的用户名>.github.io/epg-m3u/epg.xml.gz
   ```

## 自动刷新

`.github/workflows/build-epg.yml` 每天 00:00 UTC（北京时间 08:00）自动：
- 抓 5 个上游 EPG 源（可 `--sources` 改）
- 按 M3U 的 tvg-id 匹配频道
- 切出「过去 7 天 + 未来 3 天」时间窗
- `--autofill` 给上游没覆盖到的 tvg-id 补占位节目（不白屏）
- 生成 `epg.xml` + `epg.gz` 并部署到 GitHub Pages

## 参数

```
python3 epg_build.py --m3u 你的.m3u --out epg.xml --gzip --autofill \
    --past 7 --future 3 [--sources url1,url2]
```

## 数据源（默认并集）

- `epg.zsdc.eu.org/t.xml.gz`
- `atsushi444/iptv-epg`
- `epg.pw/xmltv/epg_CN.xml.gz` / `epg.xml.gz` / `epg_HK.xml.gz`

## 说明

- 输出 `channel id` = M3U 里的 `tvg-id`，App 按 tvg-id 精确匹配
- 节目 `start/stop` 时区 `+0800`
- 纯流名（无 tvg-id）的条目不参与匹配，也不补占位（保持体积可控）
