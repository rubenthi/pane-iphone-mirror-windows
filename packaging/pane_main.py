import sys

if len(sys.argv) == 3 and sys.argv[1] == '--smoke-test':
    from handset.smoke import run
    sys.exit(run(sys.argv[2]))
else:
    from handset.app import main
    main()
