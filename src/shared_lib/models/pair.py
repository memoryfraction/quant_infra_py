from dataclasses import dataclass
from underlying import Underlying

@dataclass
class Pair:
    underlying1: Underlying
    underlying2: Underlying
    score: float = 0.0

    def __post_init__(self):
        # 确保两个 Underlying 的类型相同
        if self.underlying1.type != self.underlying2.type:
            raise ValueError(
                f"Underlying types must match. Got {self.underlying1.type} and {self.underlying2.type}"
            )
        # 确保 score 在 0-100 之间
        if not (0 <= self.score <= 100):
            raise ValueError(f"Score must be between 0 and 100. Got {self.score}")

    def __str__(self):
        return f"Pair(underlying1={self.underlying1}, underlying2={self.underlying2}, score={self.score})"