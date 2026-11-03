class _App:
    def task(self, **kwargs):
        return lambda fn: fn


app = _App()
