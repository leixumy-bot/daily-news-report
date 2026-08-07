"""Base data model and collector interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class NewsItem:
    """A single news item from any source."""

    source: str
    title: str
    body: str = ""
    url: str = ""
    publish_time: str = ""

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "title": self.title,
            "body": self.body[:300],
            "url": self.url,
        }


class BaseCollector(ABC):
    """Template for all collectors. Each subclass handles one source."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def collect(self) -> list[NewsItem]:
        """Core fetch logic. Can raise on network failure."""

    def safe_collect(self, timeout: int = 0) -> tuple[list[NewsItem], str]:
        """Wrapper: returns (items, error_msg). Never raises.

        If timeout > 0, the collector will be killed if it exceeds the timeout.
        """
        if timeout <= 0:
            try:
                items = self.collect()
                return items, ""
            except Exception as e:
                return [], f"[{self.name}] {type(e).__name__}: {str(e)[:200]}"

        from concurrent.futures import ThreadPoolExecutor, TimeoutError

        pool = ThreadPoolExecutor(max_workers=1)
        fut = pool.submit(self.collect)
        try:
            items = fut.result(timeout=timeout)
            return items, ""
        except TimeoutError:
            fut.cancel()
            return [], f"[{self.name}] TIMEOUT after {timeout}s"
        except Exception as e:
            return [], f"[{self.name}] {type(e).__name__}: {str(e)[:200]}"
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
