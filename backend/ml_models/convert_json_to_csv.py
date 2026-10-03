"""
Convert arXiv JSON metadata to CSV format for training.

The Kaggle dataset provides arxiv-metadata-oai-snapshot.json
This script converts it to a CSV with columns: title, abstract, categories
"""

import json
import csv
import sys
from pathlib import Path

def convert_json_to_csv(json_file, csv_file, limit=None):
    """
    Convert arXiv JSON metadata to CSV.
    
    Args:
        json_file: Path to arxiv-metadata-oai-snapshot.json
        csv_file: Path to output arxiv.csv
        limit: Optional limit on number of records (for testing)
    """
    
    print(f"Reading JSON from: {json_file}")
    print(f"Writing CSV to: {csv_file}")
    
    count = 0
    skipped = 0
    
    with open(json_file, 'r', encoding='utf-8') as f_in, \
         open(csv_file, 'w', newline='', encoding='utf-8') as f_out:
        
        writer = csv.DictWriter(f_out, fieldnames=['title', 'abstract', 'categories'])
        writer.writeheader()
        
        for line_num, line in enumerate(f_in, 1):
            if limit and count >= limit:
                break
            
            try:
                record = json.loads(line.strip())
                
                # Extract relevant fields
                title = record.get('title', '').strip()
                abstract = record.get('abstract', '').strip()
                categories = record.get('categories', '').strip()
                
                # Skip if missing required fields
                if not title or not categories:
                    skipped += 1
                    continue
                
                # Write to CSV
                writer.writerow({
                    'title': title,
                    'abstract': abstract,
                    'categories': categories
                })
                
                count += 1
                
                # Progress indicator
                if count % 10000 == 0:
                    print(f"  Processed {count:,} records...")
                
            except json.JSONDecodeError:
                skipped += 1
                if skipped % 10000 == 0:
                    print(f"  Skipped {skipped:,} invalid records...")
                continue
            except Exception as e:
                print(f"  Error on line {line_num}: {e}")
                skipped += 1
                continue
    
    print(f"\n✓ Conversion complete")
    print(f"  Records written: {count:,}")
    print(f"  Records skipped: {skipped:,}")
    
    return count

if __name__ == "__main__":
    data_dir = Path(__file__).parent / "data"
    json_file = data_dir / "arxiv-metadata-oai-snapshot.json"
    csv_file = data_dir / "arxiv.csv"
    
    if not json_file.exists():
        print(f"❌ JSON file not found: {json_file}")
        sys.exit(1)
    
    print("="*70)
    print("CONVERTING ARXIV METADATA JSON TO CSV")
    print("="*70)
    print()
    
    try:
        records = convert_json_to_csv(str(json_file), str(csv_file))
        print(f"\nOutput file: {csv_file}")
        print(f"File size: {csv_file.stat().st_size / (1024**3):.2f} GB")
        print("\n✅ Conversion successful!")
        
    except Exception as e:
        print(f"\n❌ Conversion failed: {e}")
        sys.exit(1)
