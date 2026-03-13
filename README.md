# Related Party Transaction Checker

自动识别越南公司与中国公司之间的关联交易关系。

## 功能

- 对每对公司执行 10 次 DuckDuckGo 搜索
- 使用多语言关键词过滤证据（中/英/越）
- 调用 Claude API 判断关联关系
- 支持断点续跑
- 自动保存检查点

## 安装

```bash
pip install -r requirements.txt
```

## 使用

```bash
# 设置 API Key
export ANTHROPIC_API_KEY="your-api-key"

# 运行
python related_party_checker.py --input input.xlsx --output output.xlsx
```

## 输入格式

Excel 文件需包含以下两列：
- `vietnam_company`: 越南公司英文名
- `china_company`: 中国公司英文名

## 输出字段

| 字段 | 说明 |
|------|------|
| conclusion | 结论: 关联/不关联/无法判断 |
| relation_type | 关系类型 |
| confidence | 置信度: 高/中/低 |
| evidence_quote | 支持证据引用 |
| search_urls | 搜索结果 URL |

## 关联关系判定标准

符合以下任一条件即构成关联：
1. 一方持有另一方 ≥25% 股权
2. 存在共同实际控制人或母公司
3. 董事/监事/高管人员重叠
4. 注册地址和联系方式完全相同
5. FDI 投资关系