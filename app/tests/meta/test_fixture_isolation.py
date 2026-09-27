import pytest

@pytest.fixture
def sample():
    return list()

class TestIsolation:
    def test_modify(self, sample):
        sample.append(1)
        assert sample == [1]

    def test_fresh(self, sample):
        assert sample == []
