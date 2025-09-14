import os
import sys
import asyncio

GLOBAL_VAR = "Hello"

def decorator(func):
    def wrapper(*args, **kwargs):
        print("Decorator before call")
        result = func(*args, **kwargs)
        print("Decorator after call")
        return result
    return wrapper

class MyClass:
    def __init__(self, name):
        self.name = name

    def greet(self):
        return f"Hello, {self.name}"

@decorator
def my_function(a, b):
    """This is a sample function."""
    list_comp = [i*i for i in range(a, b)]
    return sum(list_comp)

async def async_function():
    print("Async function start")
    await asyncio.sleep(1)
    print("Async function end")

def generator_function(n):
    for i in range(n):
        yield i

if __name__ == "__main__":
    instance = MyClass("World")
    print(instance.greet())
    print(my_function(1, 10))
    for i in generator_function(5):
        print(i)
    asyncio.run(async_function())