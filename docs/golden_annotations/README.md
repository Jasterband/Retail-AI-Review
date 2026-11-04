# 黄金集人工标注

存放目录（与代码/样例照片分离）：

```
docs/golden_annotations/
  hall-183/annotations.json
  micro-000606/annotations.json
```

## 打开界面

先启动服务：

```bash
uvicorn app.main:app --reload --port 8000
```

浏览器打开：**http://127.0.0.1:8000/annotate/**

当前内置场次：

| 场次 | 说明 |
|------|------|
| `hall-183` | 大讲堂江苏大众 183 |
| `micro-000606` | 微型太极东大街 000606 |

## 怎么标

1. 左栏切换场次 / 材料  
2. **四点框**：选标签后依次点 **左上 → 右上 → 右下 → 左下** 四个顶点；可拖顶点微调  
3. **点人头**：全景照片单击标人；人数自动等于点数  
4. 右侧可填 OCR 真值（年份、讲题、门店等）  
5. 「标记本张完成」→ 「保存当前场次」

坐标均为相对图宽高 `0~1`。框结构：`{ label, text, quad:[{x,y}×4], x,y,w,h }`（后四项为外接矩形，便于兼容）。

## API

- `GET /v1/annotate/sessions`
- `GET /v1/annotate/sessions/{id}`
- `GET /v1/annotate/sessions/{id}/image?file=`
- `GET|PUT /v1/annotate/sessions/{id}/annotations`
