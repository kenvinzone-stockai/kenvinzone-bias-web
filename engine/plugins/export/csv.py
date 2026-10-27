"""
Market Bias Platform — CSV Export Plugin
"""
import pandas as pd
from plugins.export.base import ExportPlugin

class CSVExportPlugin(ExportPlugin):
    @property
    def name(self) -> str:
        return "csv"
        
    @property
    def extension(self) -> str:
        return ".csv"
        
    def export(self, data: pd.DataFrame, file_path: str) -> None:
        data.to_csv(file_path, index=False)
