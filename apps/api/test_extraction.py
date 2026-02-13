#!/usr/bin/env python3
"""Test AI extraction on the payment tracking sheet."""
import ai_worker
import json
import sys

file_path = "/Users/luckyogogo/Personal-Project/Audit_app/uploads/WhatsApp Image 2026-02-06 at 11.39.02.jpeg"
mime_type = "image/jpeg"

print("Testing AI extraction on payment tracking sheet...")
print("=" * 70)

try:
    print("\n📄 Processing file (this may take 30-60 seconds)...")
    ocr_text, items = ai_worker.process_file_batch(file_path, mime_type)
    
    print(f"\n✓ Extraction completed!")
    print(f"\nOCR Text preview (first 300 chars):")
    print("-" * 70)
    print(ocr_text[:300] if ocr_text else "[No text extracted]")
    print("-" * 70)
    
    print(f"\n📊 Extracted {len(items)} transaction(s):")
    print("=" * 70)
    
    if items:
        for i, item in enumerate(items[:5], 1):  # Show first 5
            print(f"\nTransaction {i}:")
            print(f"  Amount: {item.get('amount', 'N/A')}")
            print(f"  Currency: {item.get('currency', 'N/A')}")
            print(f"  Date: {item.get('date', 'N/A')}")
            print(f"  Vendor: {item.get('vendor', 'N/A')}")
            print(f"  Description: {item.get('description', 'N/A')}")
            print(f"  Reference: {item.get('reference', 'N/A')}")
            print(f"  Category: {item.get('category', 'N/A')}")
            print(f"  Type: {item.get('type', 'N/A')}")
        
        if len(items) > 5:
            print(f"\n... and {len(items) - 5} more transactions")
        
        print(f"\n📝 Full JSON output:")
        print(json.dumps(items, indent=2))
    else:
        print("\n⚠️  No transactions extracted. The AI model may need:")
        print("   - Better lighting/image quality")
        print("   - Clearer handwriting")
        print("   - Or to fallback to Gemini API")
        
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
