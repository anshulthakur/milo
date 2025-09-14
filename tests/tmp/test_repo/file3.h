#ifndef FILE3_H
#define FILE3_H

#include <stdio.h>
#include <stdlib.h>

#define MAX_VALUE 100

typedef struct {
    int id;
    char* name;
} MyStruct;

typedef struct __attribute__((__packed__)) {
    char c;
    int i;
} PackedStruct;

extern int global_variable;

struct test_struct {
    char a;
    int b;
};

void function1(int arg1, char *arg2);
int function2(void);

static inline int inline_function(int x) {
    return x * x;
}

#endif /* FILE3_H */