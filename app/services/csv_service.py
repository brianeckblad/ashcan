"""CSV file service for reading and writing inventory data."""
import csv
import fcntl
import os
import shutil
import logging
import tempfile
import traceback
from contextlib import contextmanager
from pathlib import Path
from app.utils.whatnot_validators import WHATNOT_FIELD_VALIDATION, METADATA_FIELDS, WHATNOT_FIELD_NAMES, METADATA_FIELD_NAMES
from app.utils.ebay_validators import EBAY_FIELD_NAMES

# Metadata fields specific to eBay listings in the CSV
EBAY_METADATA_FIELDS = [
    METADATA_FIELD_NAMES['EBAY_ITEM_ID'],
    'eBay Listing Mode',  # 'list' (now) or 'future' (18 days)
    'eBay Schedule Date',  # ISO datetime string for scheduled listings
]

# Whatnot listing-specific fields (per-item settings)
WHATNOT_LISTING_FIELDS = [
    'Auction Starting Price',  # Starting price for WhatNot auctions
]

# eBay item-specific fields (per-item settings)
EBAY_ITEM_FIELDS = [
    'eBay Category ID',       # eBay category code (e.g., 259104)
    'eBay Category Name',     # Human-readable category name
    'eBay Format',            # 'FixedPrice' or 'Auction'
    'eBay Duration',          # 'GTC', 'Days_7', 'Days_10', etc.
    'eBay Condition ID',      # Numeric eBay condition (e.g., 2750 = Like New)
    'eBay Weight (lbs)',      # Item weight in pounds
    'eBay Weight (oz)',       # Item weight in ounces
    'eBay Package Length',    # Package length in inches
    'eBay Package Width',     # Package width in inches
    'eBay Package Depth',     # Package depth in inches
    'eBay Immediate Pay',     # 'TRUE' or 'FALSE'
]

# eBay Item Specifics (C: prefixed) — auto-generated from EBAY_FIELD_NAMES
EBAY_ITEM_SPECIFICS_FIELDS = [
    v for v in EBAY_FIELD_NAMES.values() if v.startswith('C:')
]

from app.models.comic import Comic

# Get logger for this module
logger = logging.getLogger(__name__)


class CSVService:
    """
    Low-level service for CSV file input and output.

    Manages reading, writing, and schema management for the comic inventory
    CSV file. Handles automatic schema migrations when new columns are needed
    and preserves column order across updates for Whatnot compatibility.
    """

    def __init__(self, csv_file_path):
        """
        Initialize the CSVService with a target CSV file path and caching.

        Args:
            csv_file_path (str or Path): The path to the CSV inventory file.
        """
        self.csv_file_path = Path(csv_file_path)
        self._cached_fieldnames = None  # Cache for preserving column order

        # Performance caching: Cache parsed CSV data with mtime tracking
        self._cache = None  # Cached list of comic dictionaries
        self._cache_mtime = None  # File modification time when cache was built

    def _should_refresh_cache(self):
        """
        Check if cache should be refreshed based on file modification time.

        Returns:
            bool: True if cache needs refresh, False if cache is still valid
        """
        if self._cache is None:
            return True

        if not self.csv_file_path.exists():
            return True

        current_mtime = self.csv_file_path.stat().st_mtime
        if self._cache_mtime is None or current_mtime != self._cache_mtime:
            return True

        return False

    def _invalidate_cache(self):
        """Invalidate the cache after write operations."""
        self._cache = None
        self._cache_mtime = None

    def _build_fieldname_order(self, existing_fieldnames: list[str]) -> tuple[list[str], bool]:
        """Return final ordered fieldnames plus flag if migration required."""
        final_fieldnames: list[str] = []
        needs_migration = False

        # Define legacy columns to remove (duplicates of proper metadata columns)
        LEGACY_COLUMNS_TO_REMOVE = {
            'ID',  # Duplicate of SKU (not needed)
            'added_by',  # Duplicate of 'Added By'
            'date_added',  # Duplicate of 'Date Added'
            'last_modified',  # Duplicate of 'Last Modified'
            'ebay_item_id',  # Duplicate of 'eBay Item ID' (lowercase version)
            'last_exported'  # Legacy field no longer used
        }

        # Always start with metadata columns (added in defined order)
        for field in METADATA_FIELDS:
            if field not in final_fieldnames:
                final_fieldnames.append(field)
            if field not in existing_fieldnames:
                needs_migration = True
                logger.info("Migration: Adding metadata column '%s'", field)

        for field in EBAY_METADATA_FIELDS:
            if field not in final_fieldnames:
                final_fieldnames.append(field)
            if field not in existing_fieldnames:
                needs_migration = True
                logger.info("Migration: Adding eBay metadata column '%s'", field)

        # Add WhatNot listing fields
        for field in WHATNOT_LISTING_FIELDS:
            if field not in final_fieldnames:
                final_fieldnames.append(field)
            if field not in existing_fieldnames:
                needs_migration = True
                logger.info("Migration: Adding WhatNot listing column '%s'", field)

        # Add eBay item-specific fields
        for field in EBAY_ITEM_FIELDS:
            if field not in final_fieldnames:
                final_fieldnames.append(field)
            if field not in existing_fieldnames:
                needs_migration = True
                logger.info("Migration: Adding eBay item column '%s'", field)

        # Add eBay Item Specifics (C: prefixed) columns
        for field in EBAY_ITEM_SPECIFICS_FIELDS:
            if field not in final_fieldnames:
                final_fieldnames.append(field)
            if field not in existing_fieldnames:
                needs_migration = True
                logger.info("Migration: Adding eBay item specifics column '%s'", field)

        # Preserve existing custom columns after metadata (but skip legacy duplicates)
        for field in existing_fieldnames:
            if field not in final_fieldnames and field not in LEGACY_COLUMNS_TO_REMOVE:
                final_fieldnames.append(field)
            elif field in LEGACY_COLUMNS_TO_REMOVE:
                needs_migration = True  # Force migration when we find duplicates to remove
                logger.info("Migration: Removing legacy duplicate column '%s'", field)

        # Append any Whatnot-required columns missing from the file
        for field in WHATNOT_FIELD_VALIDATION.keys():
            if field not in final_fieldnames:
                final_fieldnames.append(field)
                needs_migration = True
                logger.info("Migration: Adding Whatnot column '%s'", field)

        return final_fieldnames, needs_migration

    def _get_all_fieldnames(self):
        """Return cached fieldnames, ensuring metadata + eBay columns exist."""
        if self._cached_fieldnames:
            return self._cached_fieldnames
        ordered_fields, _ = self._build_fieldname_order([])
        self._cached_fieldnames = ordered_fields
        return ordered_fields

    def initialize(self):
        """
        Prepare the CSV file for use.

        Ensures the file exists with the correct headers and performs any
        necessary migrations to the data or schema.
        """
        if not self.csv_file_path.exists():
            self.csv_file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.csv_file_path, 'w', newline='', encoding='utf-8') as csv_file:
                csv_writer = csv.DictWriter(csv_file, fieldnames=self._get_all_fieldnames(), quoting=csv.QUOTE_MINIMAL)
                csv_writer.writeheader()
        else:
            # Migrate prices if needed (remove $ signs and trailing zeros)
            self._migrate_price_format()
            # Ensure new columns (including ebay_item_id) exist even if price migration is not needed
            self._ensure_schema_columns()

    def _migrate_price_format(self):
        """
        Internal migration tool to standardize the CSV data.

        This method performs critical tasks:
        1) Standardizes price strings (removes '$' and trailing zeros).
        2) Ensures all required columns are present, adding missing ones.
        3) Preserves all existing columns (including custom metadata).
        """
        if not self.csv_file_path.exists():
            return

        try:
            # Read all rows
            rows = []
            needs_migration = False

            # Required fieldnames: metadata + Whatnot fields
            required_fieldnames = METADATA_FIELDS + list(WHATNOT_FIELD_VALIDATION.keys())

            with open(self.csv_file_path, 'r', newline='', encoding='utf-8') as csv_file:
                reader = csv.DictReader(csv_file)
                original_fieldnames = list(reader.fieldnames or [])

                final_fieldnames, needs_migration = self._build_fieldname_order(original_fieldnames)

                # Cache the fieldnames for future writes
                self._cached_fieldnames = final_fieldnames

                for row in reader:
                    # Migrate data from legacy duplicate columns to proper columns
                    # If proper column is empty but legacy column has data, copy it over
                    if not row.get('Added By') and row.get('added_by'):
                        row['Added By'] = row['added_by']
                        needs_migration = True
                    if not row.get('Date Added') and row.get('date_added'):
                        row['Date Added'] = row['date_added']
                        needs_migration = True
                    if not row.get('Last Modified') and row.get('last_modified'):
                        row['Last Modified'] = row['last_modified']
                        needs_migration = True
                    if not row.get('eBay Item ID') and row.get('ebay_item_id'):
                        row['eBay Item ID'] = row['ebay_item_id']
                        needs_migration = True

                    # Check if price needs migration (has $ sign or trailing zeros)
                    price_field = WHATNOT_FIELD_NAMES['PRICE']
                    if price_field in row and row[price_field]:
                        original_price = str(row[price_field])
                        # Remove $ and parse
                        price_str = original_price.replace('$', '').strip()
                        try:
                            price_float = float(price_str)
                            # Format: remove trailing zeros after decimal
                            new_price = f'{price_float:.2f}'.rstrip('0').rstrip('.')

                            if original_price != new_price:
                                needs_migration = True
                                row[price_field] = new_price
                        except ValueError:
                            logger.warning(f"Could not parse price '{original_price}' for {WHATNOT_FIELD_NAMES['SKU']} {row.get(WHATNOT_FIELD_NAMES['SKU'], 'unknown')}")

                    # Ensure all required fields are present with defaults
                    for field in METADATA_FIELDS + EBAY_METADATA_FIELDS + WHATNOT_LISTING_FIELDS + EBAY_ITEM_FIELDS + EBAY_ITEM_SPECIFICS_FIELDS:
                        if field not in row:
                            row[field] = ''

                    for field in WHATNOT_FIELD_VALIDATION.keys():
                        if field not in row:
                            row[field] = WHATNOT_FIELD_VALIDATION[field].get('default', '')

                    rows.append(row)

            # Only rewrite if changes are needed
            if needs_migration:
                # Backup before migration
                backup_path = self.csv_file_path.with_suffix('.csv.bak')
                shutil.copy2(self.csv_file_path, backup_path)

                with open(self.csv_file_path, 'w', newline='', encoding='utf-8') as csv_file:
                    writer = csv.DictWriter(csv_file, fieldnames=final_fieldnames, extrasaction='ignore', quoting=csv.QUOTE_ALL)
                    writer.writeheader()
                    writer.writerows(rows)
                logger.info(f"✓ Migrated {len(rows)} comics to new schema and format (removed {len([f for f in original_fieldnames if f in ['ID', 'added_by', 'date_added', 'last_modified', 'ebay_item_id', 'last_exported']])} duplicate columns)")
                self._cached_fieldnames = final_fieldnames

        except Exception as e:
            logger.error(f"Error during migration: {e}")
            # Don't fail initialization if migration fails
    
    def read_all(self):
        """
        Read all comics from the CSV file with intelligent caching.

        Parses each row into a Comic object. Gracefully handles and logs
        errors for malformed rows. Also caches fieldnames for future writes.

        Performance: Uses mtime-based caching to avoid re-parsing unchanged files.
        This provides 10-50x speedup for browse operations with 500+ items.

        Returns:
            list: A list of Comic instances.
        """
        # Check if we need to refresh cache
        if self._should_refresh_cache():
            comics_dict_cache = []

            if self.csv_file_path.exists():
                with open(self.csv_file_path, 'r', newline='', encoding='utf-8') as csv_file:
                    reader = csv.DictReader(csv_file)

                    # Cache the current fieldnames to preserve them on writes
                    if reader.fieldnames and not self._cached_fieldnames:
                        self._cached_fieldnames = list(reader.fieldnames)

                    for row in reader:
                        try:
                            # Cache raw dict, parse on demand
                            comics_dict_cache.append(dict(row))
                        except Exception as e:
                            logger.error(f"Error parsing comic row: {e}")
                            continue

                # Update cache
                self._cache = comics_dict_cache
                self._cache_mtime = self.csv_file_path.stat().st_mtime if self.csv_file_path.exists() else None
                logger.debug(f"CSV cache refreshed: {len(self._cache)} items")
            else:
                self._cache = []
                self._cache_mtime = None

        # Parse cached dicts into Comic objects
        comics = []
        for row_dict in (self._cache or []):
            try:
                comics.append(Comic.from_dict(row_dict))
            except Exception as e:
                logger.error(f"Error creating Comic from cached row: {e}")
                continue

        return comics
    
    def find_by_sku(self, sku):
        """
        Search for a comic by its unique SKU.
        
        Args:
            sku (str): The SKU to search for.
            
        Returns:
            Comic or None: The matching Comic instance, or None if not found.
        """
        comics = self.read_all()
        for comic in comics:
            if comic.sku == str(sku):
                return comic
        return None
    
    def add(self, comic):
        """
        Append a new comic to the CSV file.

        Prevents adding duplicate SKUs.

        Args:
            comic (Comic): The Comic instance to add.

        Returns:
            bool: True if the comic was added, False if SKU exists or write fails.
        """
        try:
            with self._write_lock():
                # Check for duplicate SKU before adding (under lock)
                existing = self.find_by_sku(comic.sku)
                if existing:
                    logger.error(f"Cannot add comic: SKU {comic.sku} already exists")
                    return False

                with open(self.csv_file_path, 'a', newline='', encoding='utf-8') as csv_file:
                    fieldnames = self._get_all_fieldnames()
                    row_data = comic.to_dict()
                    unknown_fields = sorted(set(row_data.keys()) - set(fieldnames))
                    if unknown_fields:
                        logger.warning("Ignoring unknown CSV fields on add: %s", unknown_fields)
                    csv_writer = csv.DictWriter(
                        csv_file,
                        fieldnames=fieldnames,
                        extrasaction='ignore',
                        quoting=csv.QUOTE_ALL,
                    )
                    csv_writer.writerow(row_data)

                # Invalidate cache after write
                self._invalidate_cache()
                return True
        except Exception as e:
            logger.error(f"Error adding comic to CSV: {e}")
            return False
    
    def update(self, sku, updated_comic):
        """
        Update an existing comic in the CSV file.

        Args:
            sku (str): The SKU of the comic to update.
            updated_comic (Comic): The updated Comic instance.

        Returns:
            bool: True if the update was successful, False otherwise.
        """
        try:
            with self._write_lock():
                comics = self.read_all()
                found = False

                for i, comic in enumerate(comics):
                    if comic.sku == str(sku):
                        comics[i] = updated_comic
                        found = True
                        break

                if not found:
                    logger.error(f"Comic with SKU {sku} not found")
                    return False

                # Atomic write: temp file + os.replace
                self._atomic_rewrite(
                    [c.to_dict() for c in comics],
                    self._get_all_fieldnames()
                )

                # Invalidate cache after write
                self._invalidate_cache()
                return True
        except Exception as e:
            logger.error(f"Error updating comic in CSV: {e}")
            logger.error(traceback.format_exc())
            return False
    
    def delete(self, sku):
        """
        Delete a comic from the CSV file.

        Args:
            sku (str): The SKU of the comic to delete.

        Returns:
            tuple: (bool, Comic or None) Success status and the deleted Comic
                   instance if found.
        """
        try:
            with self._write_lock():
                comics = self.read_all()
                deleted_comic = None

                filtered_comics = []
                for comic in comics:
                    if comic.sku == str(sku):
                        deleted_comic = comic
                    else:
                        filtered_comics.append(comic)

                if deleted_comic is None:
                    return False, None

                # Atomic write
                self._atomic_rewrite(
                    [c.to_dict() for c in filtered_comics],
                    self._get_all_fieldnames()
                )

                # Invalidate cache after write
                self._invalidate_cache()
                return True, deleted_comic
        except Exception as e:
            logger.error(f"Error deleting comic from CSV: {e}")
            return False, None

    def clear_all(self):
        """
        Permanently remove all comics from the CSV file and re-initialize
        with the latest schema headers.

        This resets cached fieldnames so the new CSV always reflects the
        current column definitions — no redeploy required.

        Returns:
            bool: True if the file was cleared successfully.
        """
        try:
            with self._write_lock():
                # Reset cached fieldnames so we get a fresh schema
                self._cached_fieldnames = None
                fieldnames = self._get_all_fieldnames()

                # Atomic rewrite with only the header
                self._atomic_rewrite([], fieldnames)

                # Invalidate data cache after write
                self._invalidate_cache()
                return True
        except Exception as e:
            logger.error(f"Error clearing CSV: {e}")
            return False

    # ------------------------------------------------------------------
    # Write-safety helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _write_lock(self):
        """Acquire an exclusive cross-process lock for CSV mutations.

        Uses ``fcntl.flock`` on a sibling ``<csv>.lock`` file so multiple
        gunicorn workers serialize their read-modify-rewrite operations.
        """
        self.csv_file_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.csv_file_path.with_suffix(self.csv_file_path.suffix + '.lock')
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)

    def _atomic_rewrite(self, rows, fieldnames):
        """Write ``rows`` to the CSV atomically via a temp file + ``os.replace``.

        Guarantees that a crash mid-write leaves the original file intact
        rather than truncated. Must be called while holding ``_write_lock``.
        """
        target_dir = self.csv_file_path.parent
        fd, tmp_path = tempfile.mkstemp(
            prefix='.' + self.csv_file_path.name + '.',
            suffix='.tmp',
            dir=str(target_dir),
        )
        try:
            with os.fdopen(fd, 'w', newline='', encoding='utf-8') as tmp_file:
                writer = csv.DictWriter(
                    tmp_file,
                    fieldnames=fieldnames,
                    extrasaction='ignore',
                    quoting=csv.QUOTE_ALL,
                )
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, str(self.csv_file_path))
        except Exception:
            # Clean up the temp file if the write/rename failed
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _ensure_schema_columns(self):
        """Add missing required columns (metadata + eBay) without rewriting unchanged data."""
        try:
            if not self.csv_file_path.exists():
                return

            with open(self.csv_file_path, 'r', newline='', encoding='utf-8') as csv_file:
                reader = csv.DictReader(csv_file)
                original_fieldnames = list(reader.fieldnames or [])

            final_fieldnames, needs_migration = self._build_fieldname_order(original_fieldnames)
            if not needs_migration:
                return

            # Read rows
            with open(self.csv_file_path, 'r', newline='', encoding='utf-8') as csv_file:
                reader = csv.DictReader(csv_file)
                rows = list(reader)

            # Add missing columns with blank defaults
            for row in rows:
                for field in final_fieldnames:
                    if field not in row:
                        row[field] = ''

            # Backup and rewrite with new headers
            backup_path = self.csv_file_path.with_suffix('.csv.bak')
            shutil.copy2(self.csv_file_path, backup_path)

            with open(self.csv_file_path, 'w', newline='', encoding='utf-8') as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=final_fieldnames, extrasaction='ignore', quoting=csv.QUOTE_ALL)
                writer.writeheader()
                writer.writerows(rows)

            self._cached_fieldnames = final_fieldnames
            logger.info("✓ Migrated CSV schema to include missing columns: %s", [f for f in final_fieldnames if f not in original_fieldnames])
        except Exception as exc:
            logger.error("Schema ensure failed: %s", exc)


def initialize_csv(csv_file_path):
    """
    Standalone helper to initialize the CSV inventory file.
    
    Args:
        csv_file_path (str or Path): Path to the CSV file.
    """
    service = CSVService(csv_file_path)
    service.initialize()
