/* Short, single-thread native benchmark. No network, business data or writes.
 * Build once: cc -O2 -march=x86-64 benchmark_single_core.c -ldl -o bench
 * Reuse the identical binary on both x86_64 hosts.
 * Run only after checking load: timeout 25s nice -n 19 taskset -c CPU ./bench
 */
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>
#include <unistd.h>

typedef int (*argon_fn)(uint32_t, uint32_t, uint32_t, const void *, size_t,
                        const void *, size_t, void *, size_t);

static double now(clockid_t clock) {
    struct timespec t;
    clock_gettime(clock, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}

int main(void) {
    void *lib = dlopen("libargon2.so.1", RTLD_NOW);
    argon_fn hash = lib ? (argon_fn)dlsym(lib, "argon2id_hash_raw") : NULL;
    if (!hash) { fputs("Existing libargon2 required\n", stderr); return 1; }
    const char password[] = "SyntheticBenchmark2026!";
    const char salt[] = "SyntheticFixedSalt";
    unsigned char digest[32];
    volatile uint64_t output = 1;
    puts("{\"round_seconds\":2,\"rounds\":3,\"argon2id\":{\"memory_kib\":7168,\"passes\":5,\"parallelism\":1},\"samples\":[");
    for (int round = 0; round < 3; round++) {
        for (int kind = 0; kind < 2; kind++) {
            uint64_t count = 0, state = 1;
            double wall_start = now(CLOCK_MONOTONIC);
            double cpu_start = now(CLOCK_PROCESS_CPUTIME_ID);
            do {
                if (kind == 0) {
                    for (int i = 0; i < 100000; i++) {
                        state ^= state << 13;
                        state ^= state >> 7;
                        state ^= state << 17;
                        state = state * UINT64_C(6364136223846793005) + 1;
                    }
                    output = state;
                    count += 100000;
                } else {
                    if (hash(5, 7168, 1, password, sizeof(password)-1, salt,
                             sizeof(salt)-1, digest, sizeof(digest)) != 0) return 2;
                    count++;
                }
            } while (now(CLOCK_MONOTONIC) - wall_start < 2.0);
            double cpu = now(CLOCK_PROCESS_CPUTIME_ID) - cpu_start;
            double wall = now(CLOCK_MONOTONIC) - wall_start;
            printf("%s{\"round\":%d,\"workload\":\"%s\",\"count\":%llu,\"wall_s\":%.6f,\"cpu_s\":%.6f,\"per_second\":%.6f}",
                   round || kind ? ",\n" : "", round+1,
                   kind ? "argon2id" : "integer_dependency_chain",
                   (unsigned long long)count, wall, cpu, count/wall);
            fflush(stdout);
            sleep(1);
        }
    }
    printf("\n],\"integer_checksum\":\"%llu\",\"synthetic_argon_digest\":\"", (unsigned long long)output);
    for (int i = 0; i < 32; i++) printf("%02x", digest[i]);
    puts("\"}");
    dlclose(lib);
    return 0;
}
