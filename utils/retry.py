"""
网络请求重试模块

提供指数退避重试功能，用于处理网络抖动等临时性错误。
"""

import asyncio
import functools
from dataclasses import dataclass
from typing import Callable, TypeVar, Any, Optional, Type, Tuple
from loguru import logger

import aiohttp


@dataclass
class RetryConfig:
    """重试配置"""
    max_retries: int = 3  # 最大重试次数
    base_delay: float = 1.0  # 基础延迟（秒）
    max_delay: float = 30.0  # 最大延迟（秒）
    exponential_base: float = 2.0  # 指数基数
    retryable_exceptions: Tuple[Type[Exception], ...] = (
        aiohttp.ClientError,
        asyncio.TimeoutError,
        ConnectionError,
        OSError,
    )
    retryable_status_codes: Tuple[int, ...] = (429, 500, 502, 503, 504)


T = TypeVar("T")


def calculate_backoff_delay(
    attempt: int,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
) -> float:
    """
    计算指数退避延迟时间

    Args:
        attempt: 当前尝试次数（从 0 开始）
        base_delay: 基础延迟
        max_delay: 最大延迟
        exponential_base: 指数基数

    Returns:
        计算后的延迟时间（秒）
    """
    delay = base_delay * (exponential_base ** attempt)
    return min(delay, max_delay)


async def retry_with_backoff(
    func: Callable[..., Any],
    *args,
    config: Optional[RetryConfig] = None,
    **kwargs,
) -> Any:
    """
    使用指数退避策略执行异步函数

    Args:
        func: 要执行的异步函数
        *args: 函数参数
        config: 重试配置，默认使用 RetryConfig()
        **kwargs: 函数关键字参数

    Returns:
        函数执行结果

    Raises:
        最后一次尝试的异常
    """
    config = config or RetryConfig()
    last_exception: Optional[Exception] = None

    for attempt in range(config.max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except config.retryable_exceptions as e:
            last_exception = e

            if attempt < config.max_retries:
                delay = calculate_backoff_delay(
                    attempt,
                    config.base_delay,
                    config.max_delay,
                    config.exponential_base,
                )
                logger.warning(
                    f"Request failed (attempt {attempt + 1}/{config.max_retries + 1}): {type(e).__name__}: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"Request failed after {config.max_retries + 1} attempts: {type(e).__name__}: {e}"
                )

    if last_exception:
        raise last_exception


def with_retry(config: Optional[RetryConfig] = None):
    """
    重试装饰器

    使用方法:
        @with_retry(RetryConfig(max_retries=3))
        async def my_async_function():
            ...

    Args:
        config: 重试配置

    Returns:
        装饰器函数
    """
    config = config or RetryConfig()

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            return await retry_with_backoff(func, *args, config=config, **kwargs)
        return wrapper

    return decorator
