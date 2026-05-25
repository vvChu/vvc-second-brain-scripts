import json
from pathlib import Path

data = {
  "type": "excalidraw",
  "version": 2,
  "source": "https://excalidraw.com",
  "elements": [],
  "appState": {"viewBackgroundColor": "#ffffff", "gridSize": 20}
}

def add_node(elements, id_prefix, type_, x, y, w, h, text, color_bg, color_stroke, font_size=16):
    shape_id = f"shape_{id_prefix}"
    text_id = f"text_{id_prefix}"
    
    lines = text.count('\n') + 1
    text_h = lines * font_size * 1.25
    text_y = y + (h - text_h) / 2
    
    elements.append({
      "type": "text",
      "id": text_id,
      "x": x + 10, "y": text_y,
      "width": w - 20, "height": text_h,
      "text": text,
      "fontSize": font_size,
      "fontFamily": 2, # Helvetica
      "textAlign": "center",
      "verticalAlign": "middle",
      "strokeColor": "#ffffff" if color_bg != "transparent" else "#1e3a5f",
      "backgroundColor": "transparent",
      "fillStyle": "solid",
      "strokeWidth": 1,
      "roughness": 0,
      "opacity": 100,
      "containerId": shape_id
    })
    
    elements.append({
      "type": type_,
      "id": shape_id,
      "x": x, "y": y,
      "width": w, "height": h,
      "strokeColor": color_stroke,
      "backgroundColor": color_bg,
      "fillStyle": "solid",
      "strokeWidth": 2,
      "roughness": 0,
      "opacity": 100,
      "boundElements": [{"id": text_id, "type": "text"}],
      "roundness": {"type": 3} if type_ == "rectangle" else None
    })
    return shape_id

def add_arrow(elements, id_arrow, points):
    elements.append({
      "type": "arrow",
      "id": id_arrow,
      "x": points[0][0], "y": points[0][1],
      "width": abs(points[1][0] - points[0][0]),
      "height": abs(points[1][1] - points[0][1]),
      "strokeColor": "#1e3a5f",
      "backgroundColor": "transparent",
      "fillStyle": "solid",
      "strokeWidth": 2,
      "roughness": 0,
      "opacity": 100,
      "points": [[0,0], [points[1][0]-points[0][0], points[1][1]-points[0][1]]],
      "endArrowhead": "arrow"
    })

elements = data["elements"]

# Center Hub
add_node(elements, "hub", "rectangle", 300, 150, 240, 80, "Hệ sinh thái\nĐịnh hướng thị trường", "#3b82f6", "#1e3a5f", 18)

# Actors (4 corners)
add_node(elements, "biz", "ellipse", 100, 50, 160, 60, "Doanh nghiệp", "#60a5fa", "#1e3a5f")
add_node(elements, "ptn", "ellipse", 580, 50, 160, 60, "Đối tác", "#60a5fa", "#1e3a5f")
add_node(elements, "cus", "ellipse", 100, 270, 160, 60, "Khách hàng", "#93c5fd", "#1e3a5f")
add_node(elements, "ntcn", "ellipse", 580, 270, 160, 60, "Nền tảng\ncông nghệ", "#93c5fd", "#1e3a5f")

# AI Integration
add_node(elements, "ai", "diamond", 350, 290, 140, 80, "AI Integration", "#ddd6fe", "#6d28d9")

# Value Chain Container (NO BOUND TEXT to avoid overlap!)
elements.append({
  "type": "rectangle",
  "id": "shape_vc",
  "x": 80, "y": 420,
  "width": 680, "height": 120,
  "strokeColor": "#94a3b8",
  "backgroundColor": "transparent",
  "fillStyle": "solid",
  "strokeWidth": 2,
  "roughness": 0,
  "opacity": 100,
  "roundness": {"type": 3}
})

# Value chain title text (Top-left of the container)
elements.append({
  "type": "text",
  "id": "text_vc_title",
  "x": 100, "y": 430,
  "width": 200, "height": 24,
  "text": "Chuỗi giá trị (Value Chain)",
  "fontSize": 16,
  "fontFamily": 2,
  "textAlign": "left",
  "verticalAlign": "top",
  "strokeColor": "#1e3a5f",
  "backgroundColor": "transparent",
  "fillStyle": "solid",
  "strokeWidth": 1,
  "roughness": 0,
  "opacity": 100
})

# Value chain steps
add_node(elements, "s1", "rectangle", 120, 460, 130, 60, "Nghiên cứu -\nPhát triển", "#fed7aa", "#c2410c", 14)
add_node(elements, "s2", "rectangle", 280, 460, 130, 60, "Sản xuất", "#fed7aa", "#c2410c", 14)
add_node(elements, "s3", "rectangle", 440, 460, 130, 60, "Phân phối", "#fed7aa", "#c2410c", 14)
add_node(elements, "s4", "rectangle", 600, 460, 130, 60, "Dịch vụ\nHậu mãi", "#fed7aa", "#c2410c", 14)

# Arrows
add_arrow(elements, "a1", [[240, 110], [320, 150]]) # Biz -> Hub
add_arrow(elements, "a2", [[600, 110], [520, 150]]) # Ptn -> Hub
add_arrow(elements, "a3", [[240, 270], [320, 230]]) # Cus -> Hub
add_arrow(elements, "a4", [[600, 270], [520, 230]]) # NTCN -> Hub

add_arrow(elements, "a5", [[420, 230], [420, 290]]) # Hub -> AI
add_arrow(elements, "a6", [[420, 370], [420, 420]]) # AI -> VC

add_arrow(elements, "a7", [[250, 490], [280, 490]]) # S1 -> S2
add_arrow(elements, "a8", [[410, 490], [440, 490]]) # S2 -> S3
add_arrow(elements, "a9", [[570, 490], [600, 490]]) # S3 -> S4

# Generate MD - Leave # Text Elements empty so Excalidraw plugin auto-populates it correctly!
md_content = f'''---
excalidraw-plugin: parsed
tags: [excalidraw]
---
==⚠  Switch to EXCALIDRAW VIEW in the MORE OPTIONS menu of this document. ⚠==

# Text Elements

%%
# Drawing
```json
{json.dumps(data, ensure_ascii=False, indent=2)}
```
%%
'''

file_path = Path(r"D:\VvC_Notes\03 - Resources\attachments\value_chain_ai.excalidraw.md")
file_path.write_text(md_content, encoding="utf-8")
print("Perfect layout generated!")
