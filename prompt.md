# 任务：批量关联交易识别脚本

我有一批越南公司与中国公司的进口交易数据，需要你帮我写一个 Python 脚本，
自动判断每对公司之间是否存在关联交易关系，并输出结构化结果到 Excel。

## 输入文件
Excel 文件路径由命令行参数传入，包含两列：
- `vietnam_company`：越南公司英文名
- `china_company`：中国公司英文名

## 处理逻辑（每对公司执行以下步骤）

### 第一步：构造搜索词，执行 10 次搜索
使用 duckduckgo-search 库（pip install duckduckgo-search），对每对公司执行以下搜索。
每次搜索取前 5 条结果，提取 title + snippet + url 拼接成文本。

【中国公司背景 — 4条】
1. `"{china_company}" shareholder parent company owner`
2. `"{china_company}" 股东 实际控制人 母公司`
3. `"{china_company}" 注册信息 法人 企业信息`
4. `"{china_company}" annual report investor relations`

【越南公司背景 — 3条】
5. `"{vietnam_company}" shareholder owner investor Vietnam`
6. `"{vietnam_company}" công ty cổ đông thành lập`
   # 越南语：公司 股东 成立
7. `"{vietnam_company}" business registration Vietnam enterprise`

【两者关联关系 — 3条】
8. `"{vietnam_company}" "{china_company}"`
   # 直接共现搜索，最容易发现显性关联
9. `"{vietnam_company}" "{china_company}" related affiliated subsidiary joint venture`
10. `"{vietnam_company}" China investment FDI foreign direct investment`
    # 越南外商投资企业普遍通过 FDI 渠道设立，此条有助于发现中资背景

### 第二步：过滤证据文本
从搜索结果中只保留包含以下关键词的句子或段落：

英文关键词：
shareholder / owner / parent / subsidiary / affiliate / investor /
related party / joint venture / wholly owned / controlled by /
beneficial owner / ultimate owner / holding company / FDI

中文关键词：
股东 / 母公司 / 子公司 / 实际控制人 / 关联方 / 控股 /
法人 / 出资人 / 外商投资 / 全资 / 参股

越南语关键词：
cổ đông / công ty mẹ / công ty con / sở hữu / đầu tư nước ngoài

将过滤后的内容去重后拼接为 evidence 字符串，最长不超过 4000 字符（超出截断）。

### 第三步：调用 Claude API 进行判断
使用以下配置初始化客户端（阿里云百炼 Anthropic 兼容接口）：

```python
import anthropic, os

client = anthropic.Anthropic(
    api_key=os.environ["DASHSCOPE_API_KEY"],
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)
```

调用时使用以下 system prompt 和 user prompt：

system:
"""
你是一名专业的关联交易审查员。你的任务是根据提供的搜索证据，
判断两家公司之间是否存在关联关系。
你只能依据用户提供的证据文本作出判断，严禁使用训练数据中的知识进行推测。
如果证据不足，必须如实输出"无法判断"。
"""

user:
"""
【证据文本】
{evidence}

（若证据文本为空，请直接输出无法判断。）

【判断任务】
根据且仅根据上方证据文本，判断以下两家公司是否存在关联交易关系：
- 越南公司：{vietnam_company}
- 中国公司：{china_company}

关联关系定义（符合任意一条即构成关联）：
1. 一方直接或间接持有另一方 25% 或以上股权
2. 两者存在共同实际控制人或共同母公司
3. 存在董事、监事或高级管理人员重叠
4. 注册地址完全相同且联系方式相同
5. 一方为另一方的外商投资设立主体（FDI 关系）

请严格按以下 JSON 格式输出，不要输出任何其他内容：
{
  "conclusion": "关联" 或 "不关联" 或 "无法判断",
  "relation_type": "母子公司" 或 "同一实控人" 或 "FDI投资关系" 或 "人员重叠" 或 "地址重叠" 或 "其他" 或 null,
  "confidence": "高" 或 "中" 或 "低",
  "evidence_quote": "从证据文本中直接引用支持结论的原句，若无则填 null",
  "missing_data": "若结论为无法判断，说明缺少哪类数据；否则填 null"
}

规则：
- 禁止根据公司名称的字面相似性推断关联关系
- 禁止使用证据文本以外的任何知识
- 若 evidence 为空或无相关内容，conclusion 必须填"无法判断"
"""

模型：`claude-sonnet-4-5`
max_tokens：512

### 第四步：解析输出并写入结果
解析 Claude 返回的 JSON，写入输出 Excel，每行包含以下字段：
vietnam_company, china_company, conclusion, relation_type,
confidence, evidence_quote, missing_data, search_urls, error

search_urls：本对公司搜索到的所有 url，用换行符分隔（方便人工复核）
error：若搜索或 API 调用失败，记录报错信息；否则填空

## 技术要求
- 每对公司处理完成后等待 3 秒再处理下一对（避免触发速率限制）
- duckduckgo-search 每条搜索词之间等待 1 秒（避免被封）
- duckduckgo-search 调用失败时自动重试一次，间隔 5 秒
- Claude API 调用失败时自动重试一次，间隔 5 秒
- 两次重试均失败则在 error 列记录错误，conclusion 填"处理失败"，继续处理下一对
- 使用 tqdm 显示进度条
- 每处理完 10 对公司，自动保存一次中间结果到 output.xlsx（防止中途崩溃丢失进度）
- 脚本支持断点续跑：若 output.xlsx 已存在，跳过其中已有结果的行，只处理剩余行
- 脚本支持命令行参数：
    python related_party_checker.py --input input.xlsx --output output.xlsx
- 脚本文件名：related_party_checker.py

## 环境变量
运行前需设置：
    export DASHSCOPE_API_KEY="你的阿里云百炼 API Key"

## 完成后请
1. 列出所有需要安装的依赖（pip install ...）
2. 输出完整的 related_party_checker.py 脚本
3. 给出一个包含 3 行假数据的 test_input.xlsx 生成命令，方便我测试