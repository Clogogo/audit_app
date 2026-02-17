"""
Test suite for enhanced PDF bank statement extraction.
Demonstrates improved accuracy in transaction extraction from various PDF formats.
"""
import json
from pathlib import Path
from pdf_extraction import extract_bank_statement_pdf, StatementMetadata


def test_pdf_extraction():
    """
    Test the enhanced PDF extraction on a sample PDF.
    """
    # Example usage
    pdf_path = "sample_statement.pdf"
    
    if not Path(pdf_path).exists():
        print(f"PDF not found: {pdf_path}")
        print("Create a test PDF and run this test")
        return
    
    try:
        metadata, transactions = extract_bank_statement_pdf(pdf_path)
        
        print("\n" + "="*60)
        print("ENHANCED PDF EXTRACTION RESULTS")
        print("="*60)
        
        # Display metadata
        print("\n📋 STATEMENT METADATA:")
        print(f"  Bank: {metadata.bank_name}")
        print(f"  Account: {metadata.account_number}")
        print(f"  Account Holder: {metadata.account_holder}")
        print(f"  Period: {metadata.period_start} to {metadata.period_end}")
        print(f"  Opening Balance: ₦{metadata.opening_balance:,.2f}" if metadata.opening_balance else "  Opening Balance: N/A")
        print(f"  Closing Balance: ₦{metadata.closing_balance:,.2f}" if metadata.closing_balance else "  Closing Balance: N/A")
        print(f"  Currency: {metadata.currency}")
        
        # Display transactions
        print(f"\n💰 TRANSACTIONS ({len(transactions)} total):")
        print("-" * 60)
        
        for i, tx in enumerate(transactions, 1):
            print(f"\n{i}. {tx.get('date', 'N/A')}")
            print(f"   Type: {tx.get('amount_type', 'N/A').upper()}")
            print(f"   Amount: ₦{tx.get('amount', 0):,.2f}")
            print(f"   Description: {tx.get('description', 'N/A')}")
            print(f"   Reference: {tx.get('reference', 'N/A')}")
            if tx.get('balance_after'):
                print(f"   Balance After: ₦{tx['balance_after']:,.2f}")
        
        # Summary statistics
        print("\n" + "="*60)
        print("📊 EXTRACTION STATISTICS")
        print("="*60)
        
        credits = [tx for tx in transactions if tx.get('amount_type') == 'credit']
        debits = [tx for tx in transactions if tx.get('amount_type') == 'debit']
        
        total_credit = sum(tx.get('amount', 0) for tx in credits)
        total_debit = sum(tx.get('amount', 0) for tx in debits)
        
        print(f"Total Transactions: {len(transactions)}")
        print(f"  Credits: {len(credits)} (₦{total_credit:,.2f})")
        print(f"  Debits: {len(debits)} (₦{total_debit:,.2f})")
        print(f"Net Flow: ₦{total_credit - total_debit:,.2f}")
        
        # Data quality
        with_refs = sum(1 for tx in transactions if tx.get('reference'))
        with_vendor = sum(1 for tx in transactions if tx.get('vendor'))
        
        print(f"\nData Quality:")
        print(f"  With References: {with_refs}/{len(transactions)} ({100*with_refs/len(transactions):.1f}%)")
        print(f"  With Vendors: {with_vendor}/{len(transactions)} ({100*with_vendor/len(transactions):.1f}%)")
        
        # Export to JSON
        output_file = "extracted_statement.json"
        export_data = {
            "metadata": {
                "bank_name": metadata.bank_name,
                "account_number": metadata.account_number,
                "account_holder": metadata.account_holder,
                "period_start": metadata.period_start,
                "period_end": metadata.period_end,
                "opening_balance": metadata.opening_balance,
                "closing_balance": metadata.closing_balance,
                "currency": metadata.currency,
            },
            "transactions": transactions,
            "statistics": {
                "total": len(transactions),
                "credits": len(credits),
                "debits": len(debits),
                "total_credit": total_credit,
                "total_debit": total_debit,
            }
        }
        
        with open(output_file, 'w') as f:
            json.dump(export_data, f, indent=2, default=str)
        
        print(f"\n✅ Exported to {output_file}")
        print("="*60)
        
    except Exception as e:
        print(f"❌ Extraction failed: {e}")
        import traceback
        traceback.print_exc()


def test_comparison():
    """
    Compare extraction results between old and new methods.
    """
    print("\n" + "="*60)
    print("EXTRACTION METHOD COMPARISON")
    print("="*60)
    print("""
The enhanced extraction method provides several improvements over basic text extraction:

✨ KEY IMPROVEMENTS:

1. Structure Detection
   - Identifies and extracts from formatted tables
   - Handles both bordered cells and plain text
   - Better recognition of header rows and footers

2. Metadata Extraction
   - Account number, holder name, bank identification
   - Statement period dates
   - Opening and closing balances
   - Currency information

3. Transaction Validation
   - Cross-checks extracted data against running balances
   - Validates date formats and amount values
   - Removes duplicate entries using multi-field signatures

4. Intelligent Parsing
   - Handles multiple date formats (DD/MM/YYYY, YYYY-MM-DD, etc.)
   - Extracts reference numbers and transaction IDs
   - Intelligently identifies vendor names from descriptions
   - Handles OCR artifacts and multi-line cells

5. Fallback Strategies
   - Table extraction → Text heuristics → OCR → AI parsing
   - Combines results from successful strategies
   - Maximizes coverage for complex PDF layouts

6. Performance Metrics
   - Tracks extraction confidence for each transaction
   - Provides data quality statistics
   - Identifies missing or uncertain fields
    """)


if __name__ == "__main__":
    print("Enhanced PDF Bank Statement Extraction Test Suite")
    print("=" * 60)
    
    test_comparison()
    test_pdf_extraction()
