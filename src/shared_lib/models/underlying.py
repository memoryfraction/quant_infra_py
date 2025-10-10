from dataclasses import dataclass
from pathlib import Path
from enums import UnderlyingType


@dataclass
class Underlying:
    name: str
    file_path: Path
    type: UnderlyingType

    def __post_init__(self):
        # 确保file_path是Path对象
        self.file_path = Path(self.file_path) if isinstance(self.file_path, str) else self.file_path
        # 确保type是UnderlyingType对象
        if isinstance(self.type, str):
            self.type = UnderlyingType(self.type)

    def __str__(self):
        return f"Underlying(name={self.name}, type={self.type.value}, path={self.file_path})"
