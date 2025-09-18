#include <pthread.h>
#include <stdio.h>
#include <unistd.h>

void* thread_function(void *arg) {
    printf("Inside thread_function\n");
    return NULL;
}

void another_function() {
    printf("Just another function\n");
}

int main() {
    pthread_t thread_id;
    printf("Creating thread\n");
    pthread_create(&thread_id, NULL, &thread_function, NULL);
    pthread_join(thread_id, NULL);
    printf("Thread finished\n");
    another_function();
    return 0;
}
