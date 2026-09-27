import asyncio
import unittest


from candyconc.services.task_manager import TaskManager


class TestTaskManagerLogging(unittest.IsolatedAsyncioTestCase):
    async def test_periodic_logging(self):
        tm = TaskManager()

        async def job(_cb):
            await asyncio.sleep(0.2)

        await tm.start(interval=0.05)
        # Logger name is the module __name__: candyconc.services.task_manager
        # (src/candyconc/services/task_manager.py).
        with self.assertLogs('candyconc.services.task_manager', level='INFO') as cm:
            await tm.add(job)
            await asyncio.sleep(0.12)
        await tm.stop()
        self.assertTrue(any('running for' in m for m in cm.output))
