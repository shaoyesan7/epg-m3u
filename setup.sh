#!/usr/bin/env bash
# setup.sh — 在仓库根目录运行（已 git clone 后）
# 把用户提供的 M3U 放到 m3u/ 目录，然后 git push 触发 Actions 重新生成
set -e
cd "$(dirname "$0")"

# 1. 确保 m3u/ 目录存在
mkdir -p m3u

# 2. 如果 epg-m3u/m3u 里没有 .m3u，但 epg-m3u/epg_m3u_sample.m3u 存在，提示用户
echo "=== 仓库结构 ==="
ls -la
echo ""
echo "请把要匹配的 M3U 放到 m3u/ 目录，例如："
echo "  cp 你的直播源.m3u m3u/my.m3u"
echo ""
echo "然后运行："
echo "  git add m3u && git commit -m 'update m3u' && git push"
echo ""
echo "GitHub Actions 会每天 00:00 UTC（北京 08:00）自动重生成 epg.xml + epg.gz"
echo "部署地址：https://<你的用户名>.github.io/epg-m3u/epg.xml.gz"
echo ""
echo "在 GitHub 仓库 Settings → Pages 里选择 'Deploy from a branch' → main / root，"
echo "或等 Actions 的 deploy-pages 跑完后直接用上面那个 URL。"
