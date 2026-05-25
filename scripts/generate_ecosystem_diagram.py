import json
from pathlib import Path

data = {
  "type": "excalidraw",
  "version": 2,
  "source": "https://excalidraw.com",
  "elements": [],
  "appState": {"viewBackgroundColor": "#ffffff", "gridSize": 20}
}

def add_node(elements, id_prefix, type_, x, y, w, h, text, color_bg, color_stroke, font_size=15):
    shape_id = f"shape_{id_prefix}"
    text_id = f"text_{id_prefix}"
    
    lines = text.count('\n') + 1
    text_h = lines * font_size * 1.3
    text_y = y + (h - text_h) / 2
    
    elements.append({
      "type": "text",
      "id": text_id,
      "x": x + 10, "y": text_y,
      "width": w - 20, "height": text_h,
      "text": text,
      "fontSize": font_size,
      "fontFamily": 3, # Nunito (Vietnamese-friendly)
      "textAlign": "center",
      "verticalAlign": "middle",
      "strokeColor": "#1e293b",
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

def add_arrow(elements, id_arrow, points, start_id=None, end_id=None):
    arrow = {
      "type": "arrow",
      "id": id_arrow,
      "x": points[0][0], "y": points[0][1],
      "width": abs(points[1][0] - points[0][0]),
      "height": abs(points[1][1] - points[0][1]),
      "strokeColor": "#475569",
      "backgroundColor": "transparent",
      "fillStyle": "solid",
      "strokeWidth": 1.5,
      "roughness": 0,
      "opacity": 100,
      "points": [[0,0], [points[1][0]-points[0][0], points[1][1]-points[0][1]]],
      "endArrowhead": "arrow"
    }
    if start_id:
        arrow["startBinding"] = {"elementId": start_id, "focus": 0, "gap": 2}
    if end_id:
        arrow["endBinding"] = {"elementId": end_id, "focus": 0, "gap": 2}
    elements.append(arrow)

elements = data["elements"]

# 1. Center Hub (Market-oriented Ecosystem)
add_node(elements, "hub", "rectangle", 280, 180, 240, 90, "Hệ sinh thái\nĐịnh hướng thị trường\n(Market-oriented Ecosystem)", "#93c5fd", "#1e3a5f", 16)

# 2. Market Driver (Customer Obsession) at Top
add_node(elements, "customer", "ellipse", 310, 40, 180, 70, "Ám ảnh Khách hàng\n(Customer Obsession)", "#a7f3d0", "#047857", 14)

# 3. AI & Automation (AI-Native Cells) at Bottom
add_node(elements, "ai", "diamond", 320, 340, 160, 90, "AI & Tế bào tự trị\n(AI-Native Cells)", "#ddd6fe", "#6d28d9", 13)

# 4. Four Pillars
add_node(elements, "p1", "rectangle", 50, 90, 180, 70, "1. Năng lực lồng ghép\n(Embedded Capabilities)", "#fed7aa", "#c2410c", 13)
add_node(elements, "p2", "rectangle", 570, 90, 180, 70, "2. Sự linh hoạt chiến lược\n(Strategic Agility)", "#fed7aa", "#c2410c", 13)
add_node(elements, "p3", "rectangle", 50, 290, 180, 70, "3. Cơ chế thị trường\n& Liên minh (Allies)", "#fed7aa", "#c2410c", 13)
add_node(elements, "p4", "rectangle", 570, 290, 180, 70, "4. Dân chủ hóa thông tin\n(Democratized Info)", "#fed7aa", "#c2410c", 13)

# 5. Arrows establishing connections
# Customer Obsession drives the Hub
add_arrow(elements, "a_cus_hub", [[400, 110], [400, 180]], "shape_customer", "shape_hub")

# Hub coordinates with the 4 pillars
add_arrow(elements, "a_hub_p1", [[280, 200], [180, 160]], "shape_hub", "shape_p1")
add_arrow(elements, "a_hub_p2", [[520, 200], [620, 160]], "shape_hub", "shape_p2")
add_arrow(elements, "a_hub_p3", [[280, 250], [180, 290]], "shape_hub", "shape_p3")
add_arrow(elements, "a_hub_p4", [[520, 250], [620, 290]], "shape_hub", "shape_p4")

# Hub feeds into AI integration
add_arrow(elements, "a_hub_ai", [[400, 270], [400, 340]], "shape_hub", "shape_ai")

# Generate MD file for Obsidian
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

output_path = Path(r"D:\VvC_Notes\03 - Resources\attachments\diagram_he_sinh_thai_thi_truong.excalidraw.md")
output_path.write_text(md_content, encoding="utf-8")
print("Ecosystem Diagram generated successfully at:", output_path)
