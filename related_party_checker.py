#!/usr/bin/env python3
"""
Related Party Transaction Checker
Checks if Vietnam-China company pairs have related party relationships
"""

import argparse
import json
import os
import re
import time
from pathlib import Path

import anthropic
import pandas as pd
from ddgs import DDGS
from tqdm import tqdm

# Evidence filter keywords
EN_KEYWORDS = [
    "shareholder", "owner", "parent", "subsidiary", "affiliate", "investor",
    "related party", "joint venture", "wholly owned", "controlled by",
    "beneficial owner", "ultimate owner", "holding company", "FDI"
]
ZH_KEYWORDS = [
    "股东", "母公司", "子公司", "实际控制人", "关联方", "控股",
    "法人", "出资人", "外商投资", "全资", "参股"
]
VI_KEYWORDS = [
    "cổ đông", "công ty mẹ", "công ty con", "sở hữu", "đầu tư nước ngoài"
]
ALL_KEYWORDS = EN_KEYWORDS + ZH_KEYWORDS + VI_KEYWORDS

# Search query templates
SEARCH_TEMPLATES = {
    # China company background (4)
    "china_bg_1": '"{china_company}" shareholder parent company owner',
    "china_bg_2": '"{china_company}" 股东 实际控制人 母公司',
    "china_bg_3": '"{china_company}" 注册信息 法人 企业信息',
    "china_bg_4": '"{china_company}" annual report investor relations',
    # Vietnam company background (3)
    "vietnam_bg_1": '"{vietnam_company}" shareholder owner investor Vietnam',
    "vietnam_bg_2": '"{vietnam_company}" công ty cổ đông thành lập',
    "vietnam_bg_3": '"{vietnam_company}" business registration Vietnam enterprise',
    # Cross-reference (3)
    "cross_1": '"{vietnam_company}" "{china_company}"',
    "cross_2": '"{vietnam_company}" "{china_company}" related affiliated subsidiary joint venture',
    "cross_3": '"{vietnam_company}" China investment FDI foreign direct investment',
}

SYSTEM_PROMPT = """你是一名专业的关联交易审查员。你的任务是根据提供的搜索证据，判断两家公司之间是否存在关联关系。
你只能依据用户提供的证据文本作出判断,严禁使用训练数据中的知识进行推测。
如果证据不足,必须如实输出"无法判断"。"""

USER_PROMPT_TEMPLATE = """【证据文本】
{evidence}

(若证据文本为空,请直接输出无法判断。)

【判断任务】
根据且仅根据上方证据文本,判断以下两家公司是否存在关联交易关系:
- 越南公司:{vietnam_company}
- 中国公司:{china_company}

关联关系定义(符合任意一条即构成关联):
1. 一方直接或间接持有另一方 25% 或以上股权
2. 两者存在共同实际控制人或共同母公司
3. 存在董事、监事或高级管理人员重叠
4. 注册地址完全相同且联系方式相同
5. 一方为另一方的外商投资设立主体(FDI 关系)

请严格按以下 JSON 格式输出,不要输出任何其他内容:
{{
  "conclusion": "关联" 或 "不关联" 或 "无法判断",
  "relation_type": "母子公司" 或 "同一实控人" 或 "FDI投资关系" 或 "人员重叠" 或 "地址重叠" 或 "其他" 或 null,
  "confidence": "高" 或 "中" 或 "低",
  "evidence_quote": "从证据文本中直接引用支持结论的原句,若无则填 null",
  "missing_data": "若结论为无法判断,说明缺少哪类数据;否则填 null"
}}

规则:
- 禁止根据公司名称的字面相似性推断关联关系
- 禁止使用证据文本以外的任何知识
- 若 evidence 为空或无相关内容,conclusion 必须填"无法判断"
"""


class RelatedPartyChecker:
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.model = "claude-sonnet-4-5"

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        """Execute DuckDuckGo search with retry logic."""
        for attempt in range(2):
            try:
                with DDGS() as ddgs:
                    results = list(ddgs.text(query, max_results=max_results))
                return results
            except Exception as e:
                if attempt == 0:
                    print(f"\n  Search failed, retrying in 5s... ({e})")
                    time.sleep(5)
                else:
                    raise e
        return []

    def extract_evidence(self, results: list[dict]) -> str:
        """Filter and extract evidence from search results."""
        evidence_parts = []
        for r in results:
            text = f"{r.get('title', '')} {r.get('body', '')}"
            # Split into sentences and filter by keywords
            sentences = re.split(r'[。.!?\n]', text)
            for sentence in sentences:
                sentence = sentence.strip()
                if any(kw.lower() in sentence.lower() for kw in ALL_KEYWORDS):
                    evidence_parts.append(sentence)
        # Deduplicate and join
        evidence = " | ".join(dict.fromkeys(evidence_parts))
        # Truncate to 4000 chars
        if len(evidence) > 4000:
            evidence = evidence[:4000] + "..."
        return evidence

    def collect_urls(self, all_results: list[list[dict]]) -> str:
        """Collect all unique URLs from search results."""
        urls = set()
        for results in all_results:
            for r in results:
                if href := r.get("href"):
                    urls.add(href)
        return "\n".join(sorted(urls))

    def judge_relationship(
        self, vietnam_company: str, china_company: str, evidence: str
    ) -> dict:
        """Call Claude API to judge relationship."""
        user_prompt = USER_PROMPT_TEMPLATE.format(
            evidence=evidence,
            vietnam_company=vietnam_company,
            china_company=china_company,
        )

        for attempt in range(2):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=512,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                content = response.content[0].text
                # Parse JSON from response
                json_match = re.search(r"\{[\s\S]*\}", content)
                if json_match:
                    return json.loads(json_match.group())
                return {
                    "conclusion": "无法判断",
                    "relation_type": None,
                    "confidence": "低",
                    "evidence_quote": None,
                    "missing_data": "API返回格式错误",
                }
            except Exception as e:
                if attempt == 0:
                    print(f"\n  API call failed, retrying in 5s... ({e})")
                    time.sleep(5)
                else:
                    raise e
        return {
            "conclusion": "处理失败",
            "relation_type": None,
            "confidence": None,
            "evidence_quote": None,
            "missing_data": None,
        }

    def process_pair(
        self, vietnam_company: str, china_company: str
    ) -> dict:
        """Process a single company pair."""
        all_results = []
        all_urls = set()

        # Execute all 10 searches
        for name, template in SEARCH_TEMPLATES.items():
            query = template.format(
                vietnam_company=vietnam_company,
                china_company=china_company,
            )
            try:
                results = self.search(query)
                all_results.append(results)
                for r in results:
                    if href := r.get("href"):
                        all_urls.add(href)
                time.sleep(1)  # Rate limit between searches
            except Exception as e:
                print(f"\n  Search error ({name}): {e}")
                all_results.append([])

        # Extract evidence
        evidence = self.extract_evidence(
            [r for results in all_results for r in results]
        )

        # Judge relationship
        try:
            result = self.judge_relationship(
                vietnam_company, china_company, evidence
            )
        except Exception as e:
            result = {
                "conclusion": "处理失败",
                "relation_type": None,
                "confidence": None,
                "evidence_quote": None,
                "missing_data": None,
            }

        result["search_urls"] = "\n".join(sorted(all_urls))
        result["error"] = None if result["conclusion"] != "处理失败" else str(e)

        return result


def main():
    parser = argparse.ArgumentParser(
        description="Check related party relationships between Vietnam-China company pairs"
    )
    parser.add_argument("--input", required=True, help="Input Excel file path")
    parser.add_argument(
        "--output", default="output.xlsx", help="Output Excel file path"
    )
    args = parser.parse_args()

    # Check API key
    api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not api_key:
        raise ValueError("DASHSCOPE_API_KEY environment variable not set")

    # Read input
    df_input = pd.read_excel(args.input)
    required_cols = ["vietnam_company", "china_company"]
    if not all(col in df_input.columns for col in required_cols):
        raise ValueError(f"Input file must have columns: {required_cols}")

    # Check for existing output (resume support)
    output_cols = [
        "vietnam_company",
        "china_company",
        "conclusion",
        "relation_type",
        "confidence",
        "evidence_quote",
        "missing_data",
        "search_urls",
        "error",
    ]

    if Path(args.output).exists():
        df_output = pd.read_excel(args.output)
        processed_pairs = set(
            zip(df_output["vietnam_company"], df_output["china_company"])
        )
        print(f"Found existing output with {len(df_output)} rows, resuming...")
    else:
        df_output = pd.DataFrame(columns=output_cols)
        processed_pairs = set()

    # Initialize checker
    checker = RelatedPartyChecker(api_key)

    # Process each pair
    pairs_to_process = [
        (row["vietnam_company"], row["china_company"])
        for _, row in df_input.iterrows()
        if (row["vietnam_company"], row["china_company"]) not in processed_pairs
    ]

    print(f"Processing {len(pairs_to_process)} company pairs...")

    checkpoint_counter = 0
    for vietnam_company, china_company in tqdm(pairs_to_process):
        result = checker.process_pair(vietnam_company, china_company)

        # Add to output
        row_data = {
            "vietnam_company": vietnam_company,
            "china_company": china_company,
            **result,
        }
        df_output = pd.concat(
            [df_output, pd.DataFrame([row_data])], ignore_index=True
        )

        # Checkpoint save every 10 pairs
        checkpoint_counter += 1
        if checkpoint_counter % 10 == 0:
            df_output.to_excel(args.output, index=False)
            tqdm.write(f"  Checkpoint saved ({checkpoint_counter} pairs processed)")

        # Rate limit between pairs
        time.sleep(3)

    # Final save
    df_output.to_excel(args.output, index=False)
    print(f"\nDone! Results saved to {args.output}")


if __name__ == "__main__":
    main()