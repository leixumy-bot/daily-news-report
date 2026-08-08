"""Base data model and collector interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import multiprocessing as mp
import queue


def _collect_in_child(collector, result_queue):
    try:
        result_queue.put(("ok", collector.collect()))
    except Exception as exc:
        result_queue.put(("error", f"{type(exc).__name__}: {str(exc)[:200]}"))


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

        method = "fork" if "fork" in mp.get_all_start_methods() else "spawn"
        context = mp.get_context(method)
        result_queue = context.Queue(1)
        process = context.Process(target=_collect_in_child, args=(self, result_queue), daemon=True)
        process.start()
        try:
            process.join(timeout)
            if process.is_alive():
                process.terminate()
                process.join(2)
                return [], f"[{self.name}] TIMEOUT after {timeout}s"
            try:
                status, value = result_queue.get(timeout=1)
            except queue.Empty:
                return [], f"[{self.name}] worker exited without a result"
            if status == "ok":
                return value, ""
            return [], f"[{self.name}] {value}"
        except Exception as e:
            if process.is_alive():
                process.terminate()
                process.join(2)
            return [], f"[{self.name}] {type(e).__name__}: {str(e)[:200]}"
        finally:
            result_queue.close()
            result_queue.join_thread()
