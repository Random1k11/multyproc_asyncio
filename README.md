### Асинхронность вместе с многопоточностью в Python

Большинство современных веб-приложений завязаны на вводе и выводе данных, по типу ЗАПРОС -> ОТВЕТ и только относительно небольшая часть нуждается в сложной обработке данных, где требуется максимально использовать всю мощь процессора.
Когда вы пишете асинхроннй код на Python, весь код выполняется в одном потоке и этот поток переключается на различные события, например обрабатывает новый запрос пока делается долгий запрос в базу данных.

Но что делать если хочется в разы увеличить производительность сервера и задействовать не используемые ядра CPU? Для этого в Python есть модуль Multiprocessing он на каждом ядре запускает интерпретатор Python, что позволяет одновременно запустить не сколько экземпляров программы и увеличить скорость ее работы. Если ещё хочется эффективно обрабатывать IO операции и выжать максимум производительности стоит объединить Multiprocessing и Asyncio.

В данном случае мы создадим несколько процессов и внутри каждого будет создан свой цикл событий (event loop), созданные циклы событий будут делать асинхронные запросы для получения данных. 

Взаимодействие мужду процессами будет происходить с помощью `multiprocessing.JoinableQueue()` и  `multiprocessing.Queue()`.
-  `multiprocessing.JoinableQueue()` для создания процессов.
-  `multiprocessing.Queue()` для результатов, чтобы мы могли узнать количество успешных запросов на скачивание. 
```    
fail_count = sum(
    1 for _ in range(amount_pages) if 'failed' in result_queue.get()
)
logger.info(
    f'Done, success: {amount_pages - fail_count}/{amount_pages}, '
    f'failure: {fail_count}/{amount_pages}'
)
```

Каждый созданный объект очереди в функции `main` мы передаём в `Image(task_queue, result_queue, url, out_dir, args.mode, item))`.
```
task_queue = multiprocessing.JoinableQueue()
    result_queue = multiprocessing.Queue()
    if process_count < multiprocessing.cpu_count():
        process_count = multiprocessing.cpu_count()
    logger.info(f'Spawning {process_count} gatherers...')

    images = [
        Image(task_queue, result_queue, url, out_dir, args.mode, item)
        for _ in range(process_count)
    ]
```
Класс `Image` наследуется от `multiprocessing.Process` поэтому у мы можем вызвать у него метод start.
```
for image in images:
    image.start()
```
Далее в методе `run` определяем каким образом запускать наш парсер, синхронно или асинхронно. Из файла настроек `settings.yaml` берём количество страниц необходимое для загрузки. И через очередь распределяем их по процессам, например первый процесс получит страницы [1, 2] второй [3, 4], третий [5].

В целом работа с многопоточностью и асинхронностью не слишком отличается от написания однопоточного асинхронного кода, основное отличие это необходимость использования очередей для того, чтобы основной процесс знал когда все задачи будут выполнены. 
Для лучшего понимания поизучайте работу кода. 
Режимы запуска:
```
-m, --mode
    async or sync
-p, --process
    количество процессов
```

```Синхронный режим с 6 процессами `python image_scraper.py -m sync -p 6```
```Асинхронный режим с 8 процессами `python image_scraper.py -m async -p 8```

Если хотите использовать дебагер `pdb` можете использовать такую конструкцию:
```
import sys
import pdb

class ForkedPdb(pdb.Pdb):
    """A Pdb subclass that may be used
    from a forked multiprocessing child

    """
    def interaction(self, *args, **kwargs):
        _stdin = sys.stdin
        try:
            sys.stdin = open('/dev/stdin')
            pdb.Pdb.interaction(self, *args, **kwargs)
        finally:
            sys.stdin = _stdin
```
И в коде добавьте `ForkedPdb().set_trace()`.  
Весь код можно посмотреть: https://github.com/Random1k11/multyproc_asyncio
