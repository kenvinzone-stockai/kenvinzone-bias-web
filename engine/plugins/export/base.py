"""
Market Bias Platform — Export Plugin Base Class
"""
import abc
import pandas as pd
from typing import Any

class ExportPlugin(abc.ABC):
    """Base class for data export plugins."""
    
    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Name of the plugin (e.g. 'csv', 'json')."""
        pass
        
    @property
    @abc.abstractmethod
    def extension(self) -> str:
        """File extension (e.g. '.csv', '.json')."""
        pass
        
    @abc.abstractmethod
    def export(self, data: pd.DataFrame, file_path: str) -> None:
        """Export the given DataFrame to the file path."""
        pass
