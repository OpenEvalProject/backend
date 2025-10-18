# bioRxiv S3 Integration Notes

## Current Status

The bioRxiv S3 integration is **partially implemented** but encounters a significant challenge: **the S3 bucket uses GUID filenames, not DOI-based filenames**.

## The Problem

### Expected vs. Actual S3 Structure

**What we expected:**
```
Current_Content/January_2024/10.1101_2023.12.11.571168.meca
```

**What actually exists:**
```
Current_Content/January_2024/0003232b-6c1e-1014-bf1c-ebcdcfbe94a9.meca
```

### Why This Is a Problem

1. **Cannot directly construct S3 paths** from DOIs
2. **Website XML is Cloudflare-protected** (can't fetch from https://www.biorxiv.org/)
3. **No index file provided** in the S3 bucket to map DOIs→GUIDs
4. **Downloading all files to search is expensive**:
   - A typical month has ~4,380 papers at ~21MB each = ~92GB
   - Cost: ~$8.28 per month at $0.09/GB data transfer
   - Searching one month = downloading all files = $8+

## Solutions

### Option 1: Build a Local Index (Recommended for Bulk Processing)

For your goal of processing all bioRxiv papers, this is the best approach:

1. **One-time cost**: Download all .meca files month by month (~$625 for all 6.8TB)
2. **As you download**, extract `manifest.xml` from each file to build DOI→GUID index
3. **Store index locally** (SQLite table or JSON file)
4. **Future lookups are instant** using your local index

**Implementation:**

```python
from app.services.s3_index import build_month_index, save_index

# Build index for a month (WARNING: downloads all files in that month!)
index = build_month_index(year=2024, month_name="January")

# Save index
save_index(index, "data/biorxiv_index_202401.json")

# Result: {"10.1101/2023.12.11.571168": "0003232b-6c1e-1014-bf1c-ebcdcfbe94a9.meca", ...}
```

**Cost breakdown:**
- Per month index build: ~$8 (downloads ~92GB)
- All 84 months: ~$672 (downloads ~6.8TB)
- **But**: You need to download all papers anyway for bulk processing!
- **Benefit**: Index enables instant lookups afterward

### Option 2: Manual Download (Current Fallback)

For individual papers or initial testing:

1. Use the API to get paper metadata
2. Show user instructions to manually download PDF
3. User uploads PDF via file upload form

This is what the current implementation does (fallback in `/api/analyze/url` endpoint).

### Option 3: Incremental Index Building

Build index incrementally as users request papers:

1. User requests paper X
2. If not in index: download all files for that month, build index
3. Store month index locally
4. Future requests for papers in that month use the index

**Hybrid approach:**
- Start with manual download for early users
- Build index for frequently requested months
- Gradually build complete index over time

## Implementation Status

### ✅ Completed

1. **XML Parser** (`app/services/jats_parser.py`)
   - Parses JATS XML to markdown
   - Extracts author info with ORCID IDs and affiliations
   - Works correctly (tested with example paper)

2. **S3 Index Builder** (`app/services/s3_index.py`)
   - `build_month_index()` - downloads .meca files and extracts DOIs
   - `save_index()` / `load_index()` - persistence
   - `lookup_filename_in_index()` - DOI lookups

3. **API Integration** (`app/services/s3_fetcher.py`)
   - `get_paper_metadata_from_api()` - gets paper date from bioRxiv API
   - `construct_s3_path_from_date()` - builds expected path
   - Error handling with clear limitation explanations

4. **Dependencies**
   - boto3 (AWS S3)
   - lxml (XML parsing)

### ⚠️  Current Limitation

The `/api/analyze/url` endpoint will:
1. Try S3 fetch (will fail with clear explanation)
2. Fall back to manual download instructions

### 🚧 Next Steps

Choose one approach:

#### A. Enable Index-Based Fetching (2-3 hours)

1. Enhance index to store month/year with each DOI
2. Update `fetch_biorxiv_from_s3()` to use index
3. Create CLI tool to build indexes month-by-month
4. Start building index for recent months

```python
# Enhanced index structure
{
    "10.1101/2023.12.11.571168": {
        "filename": "0003232b-6c1e-1014-bf1c-ebcdcfbe94a9.meca",
        "month": "January",
        "year": 2025,
        "date": "2025-01-02"
    }
}
```

#### B. Keep Manual Download (Current State)

- No additional work needed
- User experience: must manually download PDFs
- Cost: $0 for S3 (no requester-pays charges)

#### C. Build Complete Index in Background

- Create async job to build index for all months
- Takes ~1-2 days to complete
- Cost: ~$672 (full bucket download)
- Afterward: instant lookups for all papers

## Recommendation

Since your goal is to **eventually process all bioRxiv papers**, I recommend:

1. **Start with manual download** for testing and initial users
2. **Build index incrementally** as you download papers for bulk processing
3. **Store index in database** (new table: `biorxiv_s3_index`)
4. **Update every month** when new papers are added to S3

This approach:
- ✅ No immediate large cost
- ✅ Builds index naturally as you process papers
- ✅ Enables fast lookups once indexed
- ✅ Scales to full bioRxiv corpus

## Example Workflow

```python
# 1. User submits bioRxiv URL
# 2. Get metadata from API
metadata = get_paper_metadata_from_api(doi)
date = metadata['date']  # "2025-01-02"

# 3. Check if we have index for that month
index = load_index(f"data/index_2025_01.json")

if doi in index:
    # We have it! Download from S3
    s3_key = f"Current_Content/January_2025/{index[doi]['filename']}"
    # ... download and process
else:
    # Don't have it - show manual download instructions
    return {
        "status": "manual_download_required",
        "message": "Please download PDF manually",
        "instructions": "..."
    }
```

## Testing

Test the JATS parser with local XML:

```bash
uv run python -c "
from app.services.jats_parser import parse_jats_xml
md = parse_jats_xml('test_paper/content/450767.xml')
print(md[:500])
"
```

Test building a small index (WARNING: costs money!):

```bash
uv run python -c "
from app.services.s3_index import build_month_index
# Test with max_files limit
index = build_month_index(2024, 'January', max_files=5)
print(f'Indexed {len(index)} papers')
"
```
