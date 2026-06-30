import sys
import builtins
builtins.input = lambda prompt: "1"

import main2
main2.main()
