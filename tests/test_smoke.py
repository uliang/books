from books import main


def test_main_runs(capsys):
    main()
    assert "Hello from books!" in capsys.readouterr().out
