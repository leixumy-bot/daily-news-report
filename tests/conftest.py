"""pytest 共享配置：把项目根加入 sys.path。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
