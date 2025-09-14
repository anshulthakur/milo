#include "file3.h"

int global_variable = 42;

void function1(int arg1, char *arg2) {
    printf("Function 1 called with %d and %s\n", arg1, arg2);
    for (int i = 0; i < arg1; i++) {
        if (i % 2 == 0) {
            puts("Even");
        } else {
            puts("Odd");
        }
    }
}

int function2(void) {
    MyStruct s;
    s.id = 1;
    s.name = "Test";
    printf("Function 2 called with struct: id=%d, name=%s\n", s.id, s.name);
    return inline_function(global_variable);
}

int main(int argc, char *argv[]) {
    function1(5, "hello");
    int result = function2();
    printf("Result from function2: %d\n", result);
    return 0;
}