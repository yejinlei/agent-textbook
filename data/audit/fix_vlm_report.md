# OCR VLM 精修报告（multi_lesson_page）

处理模式：落地修改
成功 4 / 失败 0 / 跳过 0

## 明细

- `47eee424:026` 《马诗》 p62-62  修复 2/2 篇
  - merge_note: p62 马诗与石灰吟同页，原提取文本将石灰吟末两句误并入马诗，且混入了注释内容
  - lessons[0] 《马诗》 -> involved[0] 47eee424:026 (27 字, conf=0.98)
  - lessons[1] 《石灰吟》 -> involved[1] 47eee424:027 (35 字, conf=0.98)
- `95fe99ed:016` 《四时田园杂兴（其二十五）》 p6-6  修复 2/2 篇
  - merge_note: 四时田园杂兴（其二十五）与宿新市徐公店同页
  - lessons[0] 《四时田园杂兴（其二十五）》 -> involved[0] 95fe99ed:016 (35 字, conf=0.95)
  - lessons[1] 《宿新市徐公店》 -> involved[1] 95fe99ed:017 (35 字, conf=0.95)
- `8a551db2:016` 《暮江吟》 p38-38  修复 2/2 篇
  - merge_note: 第38页包含《暮江吟》和《题西林壁》两首古诗
  - lessons[0] 《暮江吟》 -> involved[0] 8a551db2:016 (35 字, conf=0.98)
  - lessons[1] 《题西林壁》 -> involved[1] 8a551db2:017 (35 字, conf=0.98)
- `725c537b:002` 《绝句》 p6-6  修复 2/2 篇
  - merge_note: 绝句与惠崇春江晚景同页，属古诗三首中的前两首
  - lessons[0] 《绝句》 -> involved[0] 725c537b:002 (27 字, conf=0.98)
  - lessons[1] 《惠崇春江晚景》 -> involved[1] 725c537b:003 (35 字, conf=0.98)
