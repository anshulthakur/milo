
void my_callback_handler() {
    // A callback function
}

void another_callback() {
    // Another callback
}

void register_callback(void (*cb)()) {
    cb();
}

void main() {
    int my_local_var = 10;
    register_callback(my_callback_handler);
    register_callback(another_callback);
    
    // This should be filtered out
    register_callback(my_local_var); 
}
