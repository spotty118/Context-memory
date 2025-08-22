"""
Worker management and entry point for background workers.
"""
import sys
import signal
import argparse
from typing import List, Optional
import structlog
from rq import Worker

from app.workers.queue import create_worker, QueueNames, queues
from app.workers.scheduler import initialize_scheduler, shutdown_scheduler
from app.core.config import settings

logger = structlog.get_logger(__name__)

class WorkerManager:
    """Manages worker processes and lifecycle."""
    
    def __init__(self):
        self.worker: Optional[Worker] = None
        self.running = False
    
    def start_worker(self, queue_names: List[str], with_scheduler: bool = False):
        """
        Start a worker process.
        
        Args:
            queue_names: List of queue names to process
            with_scheduler: Whether to start the scheduler alongside the worker
        """
        logger.info("starting_worker", queues=queue_names, with_scheduler=with_scheduler)
        
        try:
            # Initialize scheduler if requested
            if with_scheduler:
                scheduler_result = initialize_scheduler()
                logger.info("scheduler_initialized", **scheduler_result)
            
            # Create and start worker
            self.worker = create_worker(queue_names)
            self.running = True
            
            # Set up signal handlers for graceful shutdown
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)
            
            logger.info("worker_started", worker_name=self.worker.name)
            
            # Start processing jobs
            self.worker.work(with_scheduler=with_scheduler)
        
        except KeyboardInterrupt:
            logger.info("worker_interrupted")
            self.stop_worker()
        
        except Exception as e:
            logger.exception("worker_start_failed")
            raise
    
    def stop_worker(self):
        """Stop the worker gracefully."""
        if self.worker and self.running:
            logger.info("stopping_worker", worker_name=self.worker.name)
            
            try:
                # Stop the worker
                self.worker.request_stop()
                self.running = False
                
                # Shutdown scheduler if it was running
                shutdown_result = shutdown_scheduler()
                logger.info("scheduler_shutdown", **shutdown_result)
                
                logger.info("worker_stopped")
            
            except Exception as e:
                logger.exception("worker_stop_failed")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info("shutdown_signal_received", signal=signum)
        self.stop_worker()
        sys.exit(0)

def main():
    """Main entry point for worker processes."""
    parser = argparse.ArgumentParser(description="Context Memory Gateway Worker")
    
    parser.add_argument(
        "--queues",
        nargs="+",
        default=["default"],
        choices=list(QueueNames.__dict__.values()),
        help="Queue names to process"
    )
    
    parser.add_argument(
        "--with-scheduler",
        action="store_true",
        help="Start scheduler alongside worker"
    )
    
    parser.add_argument(
        "--list-queues",
        action="store_true",
        help="List available queues and exit"
    )
    
    args = parser.parse_args()
    
    if args.list_queues:
        logger.info("Available queues:")
        for name in QueueNames.__dict__.values():
            if not name.startswith("_"):
                queue = queues.get(name)
                if queue:
                    logger.info("queue_status", name=name, job_count=len(queue))
        return
    
    # Start worker
    manager = WorkerManager()
    manager.start_worker(args.queues, args.with_scheduler)

if __name__ == "__main__":
    main()

