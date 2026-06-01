from dados import remover_nulos_finais

def test_remover_nulos_finais():
    entrada = [1, 2, None, None]

    resultado = remover_nulos_finais(entrada)

    assert resultado == [1, 2]


print(test_remover_nulos_finais())


