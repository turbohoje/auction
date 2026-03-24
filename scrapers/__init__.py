from .rbauction import RBAuctionScraper
from .rollerauction import RollerAuctionScraper
from .equipbid import EquipBidScraper

SCRAPERS = {
    "rbauction": RBAuctionScraper,
    "rollerauction": RollerAuctionScraper,
    "equipbid": EquipBidScraper,
}
