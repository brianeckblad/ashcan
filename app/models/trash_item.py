"""Trash item model for deleted comics."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List
import json


@dataclass
class TrashItem:
    """
    Data model representing a comic item that has been deleted.

    When a comic is deleted, it's moved to trash rather than permanently removed,
    allowing recovery for a 30-day period. This model captures the complete
    state of the comic at deletion time, plus a timestamp for retention tracking.
    """
    sku: str
    title: str
    description: str
    quantity: int
    price: float
    category: str
    sub_category: str
    shipping_profile: str
    offerable: str
    hazmat: str
    condition: str
    comic_type: str
    cost_per_item: float = 0.0
    listing_type: str = 'For Sale'
    image_urls: List[str] = field(default_factory=list)
    deleted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self):
        """
        Convert the TrashItem to a dictionary representation.

        Returns:
            dict: Dictionary containing all trash item fields with string keys.
        """
        return {
            'sku': self.sku,
            'title': self.title,
            'description': self.description,
            'quantity': self.quantity,
            'price': self.price,
            'cost_per_item': self.cost_per_item,
            'listing_type': self.listing_type,
            'category': self.category,
            'sub_category': self.sub_category,
            'shipping_profile': self.shipping_profile,
            'offerable': self.offerable,
            'hazmat': self.hazmat,
            'condition': self.condition,
            'comic_type': self.comic_type,
            'image_urls': self.image_urls,
            'deleted_at': self.deleted_at
        }

    def to_json(self):
        """
        Convert the TrashItem to a JSON string.

        Returns:
            str: Pretty-printed JSON representation of the trash item.
        """
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data):
        """
        Create a TrashItem instance from a dictionary.

        Args:
            data (dict): Dictionary containing trash item fields.

        Returns:
            TrashItem: A new TrashItem instance with data from the dictionary.
        """
        return cls(
            sku=data.get('sku', ''),
            title=data.get('title', ''),
            description=data.get('description', ''),
            quantity=int(data.get('quantity', 0)),
            price=float(data.get('price', 0)),
            cost_per_item=float(data.get('cost_per_item', 0)),
            listing_type=data.get('listing_type', 'For Sale'),
            category=data.get('category', ''),
            sub_category=data.get('sub_category', ''),
            shipping_profile=data.get('shipping_profile', ''),
            offerable=data.get('offerable', ''),
            hazmat=data.get('hazmat', ''),
            condition=data.get('condition', ''),
            comic_type=data.get('comic_type', ''),
            image_urls=data.get('image_urls', []),
            deleted_at=data.get('deleted_at', datetime.now(timezone.utc).isoformat())
        )

    @classmethod
    def from_json(cls, json_string):
        """
        Create a TrashItem instance from a JSON string.

        Args:
            json_string (str): JSON encoded trash item data.

        Returns:
            TrashItem: A new TrashItem instance parsed from the JSON.
        """
        data = json.loads(json_string)
        return cls.from_dict(data)

    @classmethod
    def from_comic(cls, comic):
        """
        Create a TrashItem from an existing Comic instance.

        Captures the complete state of a comic at the moment it's deleted,
        including its current image URLs. Used during the deletion workflow
        to preserve the comic's data for potential restoration.

        Args:
            comic (Comic): The Comic instance being deleted.

        Returns:
            TrashItem: A new TrashItem with the comic's data and current timestamp.
        """
        from app.models.comic import Comic

        return cls(
            sku=comic.sku,
            title=comic.title,
            description=comic.description,
            quantity=comic.quantity,
            price=comic.price,
            cost_per_item=comic.cost_per_item,
            listing_type=comic.listing_type,
            category=comic.category,
            sub_category=comic.sub_category,
            shipping_profile=comic.shipping_profile,
            offerable=comic.offerable,
            hazmat=comic.hazmat,
            condition=comic.condition,
            comic_type=comic.comic_type,
            image_urls=list(comic.image_urls)
        )

    def to_comic(self):
        """
        Convert the TrashItem back into a Comic instance.

        Restores the comic to its state before deletion. The eBay item ID
        is set to empty since the listing would need to be recreated.

        Returns:
            Comic: A new Comic instance with the trashed item's data.
        """
        from app.models.comic import Comic

        return Comic(
            sku=self.sku,
            title=self.title,
            description=self.description,
            quantity=self.quantity,
            price=self.price,
            cost_per_item=self.cost_per_item,
            listing_type=self.listing_type,
            category=self.category,
            sub_category=self.sub_category,
            shipping_profile=self.shipping_profile,
            offerable=self.offerable,
            hazmat=self.hazmat,
            condition=self.condition,
            comic_type=self.comic_type,
            image_urls=self.image_urls,
            ebay_item_id=''  # Clear eBay ID since listing would need recreation
        )

    def days_in_trash(self):
        """
        Calculate how many days this item has been in the trash.
        
        Returns:
            int: Number of full days since deletion.
        """
        try:
            deleted = datetime.fromisoformat(self.deleted_at.replace('Z', '+00:00'))
            # Remove timezone info for comparison (normalize to naive UTC)
            if deleted.tzinfo is not None:
                deleted = deleted.replace(tzinfo=None)
        except (ValueError, AttributeError):
            # Fallback if parsing fails
            deleted = datetime.now(timezone.utc).replace(tzinfo=None)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        delta = now - deleted
        return delta.days

    def is_expired(self, retention_days=30):
        """
        Check if the trash item has exceeded the retention period.
        
        Args:
            retention_days (int): The number of days to keep items. Defaults to 30.
            
        Returns:
            bool: True if the item is older than the retention period.
        """
        return self.days_in_trash() >= retention_days
