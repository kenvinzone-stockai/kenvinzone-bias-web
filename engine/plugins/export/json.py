"""
Market Bias Platform — JSON Export Plugin
"""
import pandas as pd
from plugins.export.base import ExportPlugin

class JSONExportPlugin(ExportPlugin):
    @property
    def name(self) -> str:
        return "json"
        
    @property
    def extension(self) -> str:
        return ".json"
        
    def export(self, data: pd.DataFrame, file_path: str) -> None:
        data.to_json(file_path, orient="records", date_format="iso", indent=2)
