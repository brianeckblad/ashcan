"""Snapshot model for inventory backups."""
from dataclasses import dataclass
from datetime import datetime, timezone
import json


@dataclass
class Snapshot:
    """
    Data model representing a manual inventory backup (snapshot).
    
    A snapshot captures the entire state of the comic inventory at a specific
    point in time, including the CSV data and associated images. It allows
    for historical archiving and disaster recovery.
    """
    id: str  # Timestamp-based ID (YYYYMMDD_HHMMSS)
    name: str  # User-friendly name
    comic_count: int
    created_at: str
    description: str = ""

    def to_dict(self):
        """
        Convert the Snapshot instance to a dictionary.
        
        Returns:
            dict: Dictionary representation of the snapshot metadata.
        """
        return {
            'id': self.id,
            'name': self.name,
            'comic_count': self.comic_count,
            'created_at': self.created_at,
            'description': self.description
        }

    def to_json(self):
        """
        Convert the Snapshot instance to a formatted JSON string.
        
        Returns:
            str: JSON string representation.
        """
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data):
        """
        Create a Snapshot instance from a dictionary.
        
        Args:
            data (dict): Dictionary containing snapshot metadata.
            
        Returns:
            Snapshot: A new Snapshot instance.
        """
        return cls(
            id=data.get('id', ''),
            name=data.get('name', ''),
            comic_count=int(data.get('comic_count', 0)),
            created_at=data.get('created_at', ''),
            description=data.get('description', '')
        )

    @classmethod
    def from_json(cls, json_string):
        """
        Create a Snapshot instance from a JSON string.
        
        Args:
            json_string (str): JSON encoded snapshot metadata.
            
        Returns:
            Snapshot: A new Snapshot instance.
        """
        data = json.loads(json_string)
        return cls.from_dict(data)

    def formatted_date(self):
        """
        Get a human-readable representation of the snapshot creation date.
        
        Returns:
            str: Formatted date string (e.g., '2023-12-30 02:30 PM').
        """
        try:
            dt = datetime.strptime(self.id, '%Y%m%d_%H%M%S')
            return dt.strftime('%Y-%m-%d %I:%M %p')
        except (ValueError, TypeError):
            return self.created_at

    def age_days(self):
        """
        Calculate the number of days since the snapshot was created.
        
        Returns:
            int: Age in full days.
        """
        try:
            created = datetime.fromisoformat(self.created_at)
            now = datetime.now(timezone.utc)
            delta = now - created
            return delta.days
        except (ValueError, TypeError):
            return 0

    def is_expired(self, retention_days=730):  # 2 years default
        """
        Check if the snapshot has exceeded its retention period.
        
        Args:
            retention_days (int): Maximum age in days. Defaults to 730 (2 years).
            
        Returns:
            bool: True if the snapshot is older than the retention period.
        """
        return self.age_days() >= retention_days
