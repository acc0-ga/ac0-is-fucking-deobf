#include "pyembed.h"
#include <cstdio>
#include <string>
int main() {
    if (!pyembed::init()) { printf("FAIL init\n"); return 1; }
    std::string log;
    // 复现问题路径: dist\aimware_original.jar (含 \a)
    int rc = pyembed::run_obf(
        "E:\\minecraft-injector\\dist\\aimware_original.jar",
        "C:\\Users\\Alex\\AppData\\Local\\Temp\\opencode\\aimware_embed.jar",
        true, true, true, true, false, false, false, &log);
    printf("rc=%d\n", rc);
    printf("%s\n", log.c_str());
    pyembed::shutdown();
    return rc == 0 ? 0 : 1;
}
