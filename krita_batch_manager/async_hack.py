# Hack to run asyncio executor in the background, performing I/O ops there while keeping all the UI
# stuff on the main thread (Krita sometimes segfaults otherwise).

from dataclasses import dataclass
from PyQt5.QtCore import QObject, pyqtSignal, qInfo, qCritical
from typing import Self, Coroutine, Any, Generator, Never, Callable, Tuple, Literal
from threading import Thread
import asyncio

loop = asyncio.new_event_loop()

def runner():
	asyncio.set_event_loop(loop)
	loop.run_forever()
Thread(target=runner).start()

# Wrap any asyncio-enabled coroutine to run on the external thread.
@dataclass
class Wrap[T](Coroutine[Any, Any, T], Generator[Any, Any, T]):
	f: Coroutine[Any, Any, T]
	def __await__(self) -> Generator[Any, Any, T]: return self
	def __next__(self) -> Self: return self
	# wrap in a tuple since `.send(None)` is a special case
	def send(self, value: Tuple[T]) -> Never: raise StopIteration(value[0])
	def throw(self, value: Any, *args) -> Never: raise value
	def close(self) -> Never: raise GeneratorExit

# Drive a `Wrap`-using coroutine on the main thread.
class Task(QObject):
	signal = pyqtSignal(object)
	state: Literal[0] | Literal[1] | Literal[2] = 0
	coro: Generator[Wrap[Any], Any, None]

	def __init__(self, task: Coroutine[Wrap[Any], Any, None]) -> None:
		super().__init__()
		self.coro = task.__await__()
		self.signal.connect(self.resume)
		self.resume(None)

	def resume(self, value_or_exception: Tuple[Any] | Tuple[Any, None] | None) -> None:
		assert self.state != 2
		assert (value_or_exception is None) == (self.state == 0)
		self.state = 1
		try:
			if value_or_exception is None:
				operation = self.coro.__next__()
			elif len(value_or_exception) == 1:
				operation = self.coro.send(value_or_exception)
			else:
				operation = self.coro.throw(value_or_exception[0])
		except StopIteration:
			self.state = 2
			return

		async def wrapper() -> None:
			value_or_exception: Any
			try:
				value_or_exception = (await operation.f,)
			except Exception as e:
				value_or_exception = (e, None)
			try:
				self.signal.emit(value_or_exception)
			except Exception as e:
				qCritical(f"failed to emit: {str(e)}")
				return

		asyncio.run_coroutine_threadsafe(wrapper(), loop)

class TaskSet:
	tasks: list[Task] = []
	def spawn(self, task: Coroutine[Wrap[Any], Any, None]) -> None:
		self.tasks = [t for t in self.tasks if t.state < 2]
		self.tasks.append(Task(task))
