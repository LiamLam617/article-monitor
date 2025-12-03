# 文章阅读数监测系统

简单粗暴的数据监测系统，定时爬取文章阅读数。

## 安装

```bash
pip install -r requirements.txt
```

## 运行

```bash
python app.py
```

访问 http://127.0.0.1:5000

## 功能

1. **添加文章** - 输入文章链接，自动识别网站类型
2. **定时爬取** - 每6小时自动爬取一次（可在config.py中修改）
3. **数据展示** - 查看每篇文章的最新阅读数和历史趋势图
4. **手动爬取** - 随时点击按钮立即爬取所有文章

## 支持的网站

- 掘金 (juejin.cn)
- CSDN (csdn.net)
- 博客园 (cnblogs.com)
- 51CTO (51cto.com)
- 电子发烧友 (elecfans.com)
- SegmentFault (segmentfault.com)
- 简书 (jianshu.com)

## 数据存储

使用SQLite数据库，文件位置：`data/monitor.db`

## 配置

编辑 `config.py` 修改：
- 爬取间隔时间
- Flask端口
- 支持的网站列表

