# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This project identifies related party transactions between Vietnamese importers and Chinese companies. It uses web search and Claude API to determine if company pairs have ownership, control, or other relationships that would classify them as related parties under transfer pricing regulations.

## Key Files

| File | Purpose |
|------|---------|
| `prompt.md` | Detailed requirements document for the checker script |
| `top100_china_importers_2024.csv` | Vietnam importer data with company names and import values |
| `related_party_checker.py` | Main script (to be created) |

## Running the Script

```bash
# Set API key
export DASHSCOPE_API_KEY="your-api-key"

# Run with input file
python related_party_checker.py --input input.xlsx --output output.xlsx
```

## Script Architecture

The `related_party_checker.py` performs 4 steps per company pair:

1. **Search (10 queries)**: DuckDuckGo searches covering Chinese company background (4), Vietnamese company background (3), and cross-reference between both companies (3)

2. **Evidence Filtering**: Extract sentences containing ownership/control keywords in English, Chinese, and Vietnamese

3. **Claude API Judgment**: Call Claude via Alibaba Cloud DashScope API with filtered evidence to classify relationship

4. **Output**: Write results to Excel with conclusion, relation type, confidence, evidence quotes, and search URLs

## Technical Requirements

- Rate limiting: 3s between pairs, 1s between searches
- Auto-retry with 5s delay on failures
- Checkpoint saves every 10 pairs
- Resume from existing output file (skip processed rows)

## API Configuration

Uses Alibaba Cloud DashScope's Anthropic-compatible endpoint:
```python
client = anthropic.Anthropic(
    api_key=os.environ["DASHSCOPE_API_KEY"],
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)
```

Model: `claude-sonnet-4-5`

## Related Party Criteria

A relationship exists if ANY of these apply:
1. One party holds ≥25% equity in the other
2. Common ultimate controller or parent company
3. Overlapping directors/senior management
4. Identical registered address AND contact information
5. FDI relationship (Chinese investor established Vietnamese entity)