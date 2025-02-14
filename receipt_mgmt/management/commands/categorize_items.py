from django.core.management.base import BaseCommand
from django.db import transaction
from receipt_mgmt.models import Receipt
from receipt_mgmt.services.spending_categorization import categorize_receipt_items


class Command(BaseCommand):
    help = 'Categorize items in receipts using OpenAI GPT-4o-mini'

    def add_arguments(self, parser):
        parser.add_argument(
            '--receipt-id',
            type=int,
            help='Categorize items in a specific receipt by ID'
        )
        parser.add_argument(
            '--user-email',
            type=str,
            help='Categorize items for all receipts of a specific user'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Categorize items in all receipts (use with caution!)'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(
                self.style.WARNING('🔍 DRY RUN MODE - No changes will be made')
            )
        
        # Get receipts to process
        receipts = self.get_receipts(options)
        
        if not receipts:
            self.stdout.write(
                self.style.ERROR('❌ No receipts found to process')
            )
            return
        
        self.stdout.write(
            self.style.SUCCESS(f'📋 Found {len(receipts)} receipts to process')
        )
        
        # Process each receipt
        total_items_updated = 0
        total_receipts_changed = 0
        
        for i, receipt in enumerate(receipts, 1):
            self.stdout.write(f'\n📦 Processing receipt {i}/{len(receipts)} (ID: {receipt.id})')
            self.stdout.write(f'   Company: {receipt.company}')
            self.stdout.write(f'   Items: {receipt.items.count()}')
            self.stdout.write(f'   Current category: {receipt.get_receipt_type_display()}')
            
            if dry_run:
                self.stdout.write('   [DRY RUN] Would categorize items...')
                continue
            
            try:
                with transaction.atomic():
                    result = categorize_receipt_items(receipt)
                    
                    total_items_updated += result['items_updated']
                    if result['receipt_category_changed']:
                        total_receipts_changed += 1
                    
                    categorization_method = result.get('categorization_method', 'unknown')
                    method_emoji = '🤖' if categorization_method == 'item_analysis' else '🏪'
                    
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'   ✅ Updated {result["items_updated"]} items ({method_emoji} {categorization_method})'
                        )
                    )
                    
                    if result['receipt_category_changed']:
                        old_cat = Receipt.ReceiptType(result['old_receipt_category']).label
                        new_cat = Receipt.ReceiptType(result['new_receipt_category']).label
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'   📝 Receipt category: {old_cat} → {new_cat}'
                            )
                        )
                    
                    # Show category distribution
                    if result['category_distribution']:
                        self.stdout.write('   📊 Category distribution:')
                        for cat_id, count in result['category_distribution'].items():
                            cat_name = Receipt.ReceiptType(cat_id).label
                            self.stdout.write(f'      {cat_name}: {count}')
                    
                    if 'error' in result:
                        self.stdout.write(
                            self.style.ERROR(f'   ❌ Error: {result["error"]}')
                        )
                        
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'   ❌ Failed to process receipt: {e}')
                )
        
        # Summary
        self.stdout.write(f'\n{"="*50}')
        self.stdout.write(self.style.SUCCESS('📊 SUMMARY'))
        self.stdout.write(f'   Receipts processed: {len(receipts)}')
        if not dry_run:
            self.stdout.write(f'   Items updated: {total_items_updated}')
            self.stdout.write(f'   Receipt categories changed: {total_receipts_changed}')
        self.stdout.write(f'{"="*50}')

    def get_receipts(self, options):
        """Get receipts based on command options."""
        if options['receipt_id']:
            try:
                receipt = Receipt.objects.get(id=options['receipt_id'])
                return [receipt]
            except Receipt.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'❌ Receipt with ID {options["receipt_id"]} not found')
                )
                return []
        
        elif options['user_email']:
            receipts = Receipt.objects.filter(
                user__email=options['user_email']
            ).prefetch_related('items')
            return list(receipts)
        
        elif options['all']:
            # Confirm before processing all receipts
            confirm = input('⚠️  Are you sure you want to process ALL receipts? (yes/no): ')
            if confirm.lower() != 'yes':
                self.stdout.write('❌ Operation cancelled')
                return []
            
            receipts = Receipt.objects.all().prefetch_related('items')
            return list(receipts)
        
        else:
            self.stdout.write(
                self.style.ERROR(
                    '❌ Please specify --receipt-id, --user-email, or --all'
                )
            )
            return [] 