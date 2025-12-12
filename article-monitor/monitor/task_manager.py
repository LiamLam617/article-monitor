"""
任务管理器 - 异步任务队列和状态追踪
优化：将大量爬取改为后台任务，API 立即返回
"""
import asyncio
import threading
import uuid
from datetime import datetime
from typing import Dict, Optional, List
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class TaskManager:
    """任务管理器（单例模式）"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._tasks: Dict[str, Dict] = {}
        self._task_lock = threading.Lock()
        self._max_concurrent_tasks = 3  # 全局最大并发任务数
        self._current_running = 0
        self._task_queue = asyncio.Queue()
        self._worker_thread = None
        self._start_worker()
    
    def _start_worker(self):
        """启动后台工作线程"""
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker_thread.start()
            logger.info("任务管理器工作线程已启动")
    
    def _worker_loop(self):
        """工作线程循环（在新的事件循环中运行）"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._process_tasks())
    
    async def _process_tasks(self):
        """处理任务队列"""
        while True:
            try:
                # 等待任务或超时
                task_id = await asyncio.wait_for(self._task_queue.get(), timeout=1.0)
                
                # 检查并发限制（线程安全）
                while True:
                    with self._task_lock:
                        if self._current_running < self._max_concurrent_tasks:
                            break
                    await asyncio.sleep(0.5)
                
                # 获取任务（线程安全）
                with self._task_lock:
                    task = self._tasks.get(task_id)
                    if not task or task['status'] != TaskStatus.PENDING:
                        continue
                    task['status'] = TaskStatus.RUNNING
                    self._current_running += 1
                
                # 执行任务
                try:
                    await task['func'](task_id, *task.get('args', []), **task.get('kwargs', {}))
                    with self._task_lock:
                        task['status'] = TaskStatus.COMPLETED
                        task['end_time'] = datetime.now().isoformat()
                except Exception as e:
                    logger.error(f"任务执行失败 {task_id}: {e}")
                    with self._task_lock:
                        task['status'] = TaskStatus.FAILED
                        task['error'] = str(e)
                        task['end_time'] = datetime.now().isoformat()
                finally:
                    self._current_running -= 1
                    self._task_queue.task_done()
                    
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"任务处理异常: {e}")
                await asyncio.sleep(1)
    
    def submit_task(self, func, *args, **kwargs) -> str:
        """提交任务
        
        Args:
            func: 异步函数
            *args, **kwargs: 函数参数
            
        Returns:
            任务ID
        """
        task_id = str(uuid.uuid4())
        task = {
            'id': task_id,
            'status': TaskStatus.PENDING,
            'func': func,
            'args': args,
            'kwargs': kwargs,
            'start_time': datetime.now().isoformat(),
            'end_time': None,
            'progress': {},
            'error': None
        }
        
        with self._task_lock:
            self._tasks[task_id] = task
        
        # 添加到队列（使用线程安全的方式）
        # 由于工作线程有自己的事件循环，我们需要通过回调方式添加
        def add_to_queue():
            try:
                # 尝试获取工作线程的事件循环
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self._task_queue.put(task_id))
                else:
                    loop.run_until_complete(self._task_queue.put(task_id))
            except RuntimeError:
                # 如果没有事件循环，创建新的（这不应该发生，但作为后备）
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._task_queue.put(task_id))
                finally:
                    loop.close()
        
        # 如果当前线程有事件循环，直接调用；否则在新线程中调用
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 在主线程中，需要在新线程中执行
                threading.Thread(target=add_to_queue, daemon=True).start()
            else:
                # 没有运行的事件循环，直接执行
                add_to_queue()
        except RuntimeError:
            # 没有事件循环，在新线程中执行
            threading.Thread(target=add_to_queue, daemon=True).start()
        
        logger.info(f"任务已提交: {task_id}")
        return task_id
    
    def get_task(self, task_id: str) -> Optional[Dict]:
        """获取任务状态"""
        with self._task_lock:
            task = self._tasks.get(task_id)
            if task:
                return {
                    'id': task['id'],
                    'status': task['status'].value,
                    'start_time': task['start_time'],
                    'end_time': task['end_time'],
                    'progress': task.get('progress', {}),
                    'error': task.get('error')
                }
            return None
    
    def update_task_progress(self, task_id: str, progress: Dict):
        """更新任务进度"""
        with self._task_lock:
            task = self._tasks.get(task_id)
            if task:
                task['progress'].update(progress)
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        with self._task_lock:
            task = self._tasks.get(task_id)
            if task and task['status'] in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                task['status'] = TaskStatus.CANCELLED
                task['end_time'] = datetime.now().isoformat()
                return True
            return False
    
    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """清理旧任务（保留最近24小时的任务）"""
        cutoff_time = datetime.now().timestamp() - (max_age_hours * 3600)
        
        with self._task_lock:
            to_remove = []
            for task_id, task in self._tasks.items():
                try:
                    start_time = datetime.fromisoformat(task['start_time']).timestamp()
                    if start_time < cutoff_time:
                        to_remove.append(task_id)
                except (ValueError, KeyError) as e:
                    logger.debug(f"清理任务时解析时间失败 {task_id}: {e}")
                    to_remove.append(task_id)
            
            for task_id in to_remove:
                del self._tasks[task_id]
        
        if to_remove:
            logger.info(f"清理了 {len(to_remove)} 个旧任务")

# 全局任务管理器实例
_task_manager = None

def get_task_manager() -> TaskManager:
    """获取任务管理器实例"""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager

