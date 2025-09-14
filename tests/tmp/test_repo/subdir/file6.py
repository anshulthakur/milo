from collections import namedtuple

# A named tuple
Point = namedtuple('Point', ['x', 'y'])

class AnotherClass(object):
    """Another class with a static method."""
    class_var = 10

    def __init__(self, x, y):
        self.p = Point(x, y)

    @staticmethod
    def static_method():
        return "This is a static method."

    def __repr__(self):
        return f"AnotherClass(x={self.p.x}, y={self.p.y})"

def another_function(items):
    """A function with a filter and map."""
    evens = filter(lambda x: x % 2 == 0, items)
    squared = map(lambda x: x * x, evens)
    return list(squared)

# A simple generator expression
gen_exp = (x for x in range(10) if x % 3 == 0)

def main():
    ac = AnotherClass(1, 2)
    print(ac)
    print(AnotherClass.static_method())
    numbers = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    print(another_function(numbers))
    for val in gen_exp:
        print(f"Generator expression value: {val}")

if __name__ == '__main__':
    main()