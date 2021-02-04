import argparse
import asyncio
import json
import multiprocessing

import aiofiles
import requests
from aiohttp import ClientSession
from loguru import logger


class Ticker(multiprocessing.Process):

    def __init__(self, task_queue, result_queue,
                 burl, params, out_dir, mode):
        multiprocessing.Process.__init__(self)
        self.task_queue = task_queue
        self.result_queue = result_queue
        self.base_url = burl
        self.params = params
        self.out_dir = out_dir
        self.mode = mode

    async def get(self, ticker: str, session: ClientSession) -> str:
        """Make http GET request to fetch ticker data."""
        url = f'{self.base_url}{ticker}'
        logger.debug(f'{self.name} http-get for {url}')
        resp = await session.get(url, params=self.params)
        if resp.status != 200:
            logger.error(f'{self.name}:{ticker} failed, status={resp.status}')
            return ''
        logger.debug(f'Got response [{resp.status}] for URL: {url}')
        tdata = await resp.text()
        return tdata

    async def aio_process(self, ticker: str, session: ClientSession) -> str:
        """Issue GET for the ticker and write to file."""
        logger.debug(f'{self.name} processing_ticker {ticker}')
        fname = f'{self.out_dir}/{ticker}.csv'
        res = await self.get(ticker=ticker, session=session)
        if not res:
            return f'{ticker} fetch failed'
        async with aiofiles.open(fname, "a") as f:
            await f.write(res)
        return f'{ticker} fetch succeeded'

    async def asyncio_sessions(self, tickers: list) -> None:
        """Create session to concurrently fetch tickers."""
        logger.info(f'{self.name} session for {len(tickers)} tickers')
        async with ClientSession() as session:
            tasks = []
            for t in tickers:
                tasks.append(self.aio_process(ticker=t, session=session))
            results = await asyncio.gather(*tasks)

        # send result status
        for r in results:
            self.result_queue.put(r)

    def sync_process(self, tickers: list) -> None:
        for ticker in tickers:
            url = f'{self.base_url}{ticker}'
            logger.debug(f'{self.name} http-get for {url}')
            resp = requests.get(url, params=self.params)
            if resp.status_code != requests.codes.ok:
                logger.error(
                    f'{self.name}:{ticker} failed, status={resp.status_code}'
                )
                self.result_queue.put(f'{ticker} fetch failed')
                continue
            data = resp.text
            file_name = f'{self.out_dir}/{ticker}.csv'
            with open(file_name, 'w') as file:
                file.write(data)
            self.result_queue.put(f'{ticker} fetch succeeded')

    def run(self):
        proc_name = self.name
        tickers = []

        # Get all tasks
        while True:
            t = self.task_queue.get()
            if t == 'done':
                logger.debug(f'{proc_name} Received all allocated tickers')
                break
            tickers.append(t)
            self.task_queue.task_done()

        logger.info(f'{proc_name} processing {self.mode} {len(tickers)} tickers')

        # Do sync or async processing
        if self.mode == "async":
            asyncio.run(self.asyncio_sessions(tickers))
        else:
            self.sync_process(tickers)

        # Respond to None received in task_queue
        self.task_queue.task_done()

    def __str__(self):
        return 'Ticker %s.' % self.name


def parse_clargs():
    mparser = argparse.ArgumentParser(
        description='Evaluate sync vs async multiprocessing')
    mparser.add_argument('-m',
                         '--mode',
                         action='store',
                         default='sync',
                         choices=['sync', 'async'],
                         help='evaluation mode')
    mparser.add_argument('-c',
                         '--count',
                         action='store',
                         type=int,
                         default=10,
                         help='count of tickers to fetch')
    mparser.add_argument('-p',
                         '--parallel',
                         action='store',
                         type=int,
                         default=1,
                         help='multiprocessing count')
    mparser.add_argument('-t',
                         '--tickerconf',
                         action='store',
                         type=str,
                         help='ticker config file',
                         required=True)
    mparser.add_argument('-o',
                         '--outdir',
                         action='store',
                         default='tickerdata',
                         help='output directory to store downloaded tickers')

    return mparser.parse_args()


def main():

    args = parse_clargs()

    fetch_count = args.count
    process_count = args.parallel

    with open(args.tickerconf, 'r') as f:
        ticker_config = json.load(f)
    tickers_list = ticker_config['tickers']
    base_url = ticker_config['base_url']
    params = ticker_config['params']
    logger.info(f'Processing {args.mode} {fetch_count} tickers')

    # Task queue is used to send the tickers to processes
    # Result queue is used to get the result from processes
    task_q = multiprocessing.JoinableQueue()
    result_q = multiprocessing.Queue()

    if process_count > multiprocessing.cpu_count():
        process_count = multiprocessing.cpu_count()
    logger.info(f'Spawning {process_count} gatherers...')

    tickers = [
        Ticker(task_q, result_q, base_url, params, args.outdir, args.mode)
        for _ in range(process_count)
    ]
    for ticker in tickers:
        ticker.start()

    # enqueueing ticker jobs in task_queue
    for idx, item in enumerate(tickers_list):
        if idx >= fetch_count:
            break
        task_q.put(item)

    for _ in range(process_count):
        task_q.put('done')

    fail_count = sum(
        1 for _ in range(fetch_count) if 'failed' in result_q.get()
    )
    logger.info(
        f'Done, success: {fetch_count - fail_count}/{fetch_count}, '
        f'failure: {fail_count}/{fetch_count}'
    )


if __name__ == '__main__':
    main()
